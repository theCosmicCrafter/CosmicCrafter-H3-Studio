"""Bounded HTTP and verified local file transfer to one configured Studio."""
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx2

MAX_JSON = 32 * 1024**2


class StudioError(ValueError):
    def __init__(self, message, *, code='studio_error', status=None, path='', details=None):
        super().__init__(message)
        self.code, self.status, self.path, self.details = code, status, path, details or {}

    def result(self):
        return dict(code=self.code, message=str(self), status=self.status, path=self.path, details=self.details)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()


def parse(raw):
    def invalid(value):
        raise ValueError('Nonfinite JSON value')
    return json.loads(raw, parse_constant=invalid)


def _path_safe(path):
    decoded = path
    for _ in range(8):
        updated = unquote(decoded)
        if updated == decoded:
            break
        decoded = updated
    if '\\' in decoded or any(part in ('.', '..') for part in decoded.split('/')) or any(ord(c) < 32 for c in decoded):
        raise StudioError('Resource path must remain within the configured Studio origin.')


class StudioClient:
    def __init__(self, base_url, token=None, timeout=30, roots=None):
        parts = urlsplit(base_url)
        if (parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment or '\\' in base_url):
            raise StudioError('Use a Studio HTTP URL with an optional proxy prefix and no embedded credentials.')
        _path_safe(parts.path)
        if not math.isfinite(timeout) or timeout <= 0:
            raise StudioError('HTTP timeout must be positive and finite.')
        if token and any(ord(c) < 32 for c in token):
            raise StudioError('Invalid bearer environment value.')
        self.base_url, self.token = base_url.rstrip('/'), token
        self.roots = [Path(root).resolve() for root in (roots or [Path.cwd()])]
        self.http = httpx2.Client(timeout=timeout, follow_redirects=False,
                                  headers={'Authorization': 'Bearer ' + token} if token else {})

    def close(self):
        self.http.close()

    def _url(self, path):
        parts = urlsplit(path)
        if parts.scheme or parts.netloc or parts.fragment or not path.startswith('/') or path.startswith('//'):
            raise StudioError('Resource URL must be a same-origin relative path.')
        _path_safe(parts.path)
        return self.base_url + path

    def _redact(self, value):
        if isinstance(value, str):
            return value.replace(self.token, '[redacted]') if self.token else value
        if isinstance(value, dict):
            return {key: self._redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        return value

    def _error(self, status, raw):
        if 300 <= status < 400:
            raise StudioError('HTTP redirect refused; configure the final Studio URL.', code='redirect_refused', status=status)
        try:
            result = parse(raw)
        except (ValueError, UnicodeError):
            result = {}
        if status >= 400 or (isinstance(result, dict) and (result.get('ok') is False or (result.get('error') and 'state' not in result))):
            detail = result.get('error', {}) if isinstance(result, dict) else {}
            if not isinstance(detail, dict):
                detail = {'message': str(detail)}
            detail = self._redact(detail)
            if isinstance(result, dict):
                detail = {**self._redact({key: result[key] for key in ('code', 'message', 'path') if key in result}), **detail}
            diagnostics = self._redact({key: value for key, value in result.items() if key not in ('ok', 'error')}) if isinstance(result, dict) else {}
            failures = diagnostics.get('errors')
            if isinstance(failures, list) and failures and isinstance(failures[0], dict):
                detail = {**failures[0], **detail}
            raise StudioError(detail.get('message') or f'Studio HTTP {status}', code=detail.get('code', 'studio_error'),
                              status=status, path=detail.get('path', ''), details={**diagnostics, **(detail.get('details') or {})})

    def _request(self, path, *, method='GET', body=None, key=None, files=None, data=None):
        headers = {'Accept': 'application/json'}
        if key is not None:
            headers['Idempotency-Key'] = key
        content = encoded(body) if body is not None else None
        if content is not None:
            headers['Content-Type'] = 'application/json'
        try:
            with self.http.stream(method, self._url(path), content=content, headers=headers, files=files, data=data) as response:
                chunks, count = [], 0
                for chunk in response.iter_bytes():
                    count += len(chunk)
                    if count > MAX_JSON:
                        raise StudioError('Studio response exceeds the adapter limit.', code='response_too_large')
                    chunks.append(chunk)
                raw = b''.join(chunks)
                self._error(response.status_code, raw)
                return raw
        except httpx2.HTTPError as error:
            raise StudioError('Studio connection failed; retain the request key and job receipt.', code='connection_error') from error

    def json(self, path, *, method='GET', body=None, key=None):
        try:
            result = parse(self._request(path, method=method, body=body, key=key))
            if not isinstance(result, dict):
                raise ValueError('JSON object required')
            return result
        except (ValueError, UnicodeError) as error:
            if isinstance(error, StudioError):
                raise
            raise StudioError('Studio returned invalid JSON.', code='invalid_response') from error

    def bytes(self, path, *, expected_digest=None, expected_size=None):
        raw = self._request(path)
        self._verify(raw, expected_digest, expected_size)
        return raw

    @staticmethod
    def _verify(raw, checksum, size):
        if checksum is not None and hashlib.sha256(raw).hexdigest() != checksum.removeprefix('sha256:'):
            raise StudioError('Resource hash changed; refresh its manifest.', code='resource_changed')
        if size is not None and len(raw) != size:
            raise StudioError('Resource byte size differs from metadata.', code='resource_changed')

    def local_path(self, path):
        path = Path(path)
        path = (self.roots[0] / path).resolve() if not path.is_absolute() else path.resolve()
        if not any(path.is_relative_to(root) for root in self.roots):
            raise StudioError('File path is outside the configured workspace roots.', code='path_outside_roots')
        return path

    def upload(self, path, kind):
        path = self.local_path(path)
        with path.open('rb') as source:
            checksum = hashlib.file_digest(source, 'sha256').hexdigest()
        with path.open('rb') as stream:
            raw = self._request('/h3c/api/v1/assets', method='POST',
                                data={'kind': kind, 'expected_sha256': checksum},
                                files={'file': ('source', stream, 'application/octet-stream')})
        try:
            result = parse(raw)
        except (ValueError, UnicodeError) as error:
            raise StudioError('Upload returned invalid metadata.') from error
        if not isinstance(result, dict) or result.get('sha256') != checksum:
            raise StudioError('Uploaded bytes do not match the original.', code='asset_hash')
        return result

    def import_still(self, path):
        path = self.local_path(path)
        with path.open('rb') as stream:
            return parse(self._request('/h3c/stills/import', method='POST',
                                       files={'image': ('source.png', stream, 'application/octet-stream')}))

    def download(self, descriptor, destination):
        destination = self.local_path(destination)
        checksum, size = descriptor.get('sha256'), descriptor.get('size')
        if not isinstance(checksum, str) or not re.fullmatch('[a-f0-9]{64}', checksum) or type(size) is not int or size <= 0:
            raise StudioError('Download needs verified SHA-256 and byte-size metadata.')
        url = self._url(descriptor.get('download_url', ''))
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=destination.parent, suffix='.download')
        hasher, count = hashlib.sha256(), 0
        try:
            with os.fdopen(fd, 'wb') as stream, self.http.stream('GET', url) as response:
                if not 200 <= response.status_code < 300:
                    chunks, count = [], 0
                    for chunk in response.iter_bytes():
                        count += len(chunk)
                        if count > MAX_JSON:
                            raise StudioError('Studio response exceeds the adapter limit.', code='response_too_large')
                        chunks.append(chunk)
                    self._error(response.status_code, b''.join(chunks))
                for chunk in response.iter_bytes():
                    count += len(chunk)
                    if count > size:
                        raise StudioError('Download exceeds its verified byte size.')
                    hasher.update(chunk); stream.write(chunk)
                if count != size or hasher.hexdigest() != checksum:
                    raise StudioError('Download size/hash verification failed.', code='artifact_integrity')
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, destination)
            return dict(path=str(destination), sha256=checksum, size=count)
        except httpx2.HTTPError as error:
            raise StudioError('Artifact connection failed.', code='connection_error') from error
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

# Timeline pictures

In the Studio (**Open Studio** on the Timeline node), the Timeline page has **Pictures**, between Enabled references
and RefMods. Press **+ Picture** to upload one or more pictures into the Timeline itself. They take the next free
slots from `@image17` up, after the node's 16 wired inputs, in file-name order, with no upper limit. Use them like
connected pictures: mention them in any box's prompt, choose them as First frame or Last frame, and give them to Cast
entities and looks. Every picture list shows them with their thumbnail, and Enabled references can turn them off.
With more than 12 pictures, the frame and Cast pickers show a **Filter pictures** field. [Long edits](TIMELINE-LONG-EDITS.md)
covers Timelines with many pictures and short cuts.

Give a picture a title to show instead of its file name; Story uses it as the reference's name. **Replace…** uploads
another file into the same slot and keeps its title, so every mention and frame shows the new file; boxes that use it
need a render again. **Remove** takes the picture out at once and names the boxes that used it. Their mentions then
show as missing, and Undo brings the picture back. A new picture never takes a slot the Timeline still names.

On the Box page, **Upload…** under First frame and Last frame adds a picture and makes it the box's frame in one step.
On the Cast page, **Upload…** under a picture's Replace… picker and under a look's picture picker adds a picture and
uses it in the same bible edit; if that edit fails, the picture is taken out again.

When a box renders, the node loads only the pictures the box uses, with ComfyUI's own Load Image code, so a Timeline
picture renders exactly like the same file on a wired Load Image node. A box that uses a picture whose file is gone
stops with a message naming the box, the picture and the file; a picture no box uses never stops a render. RefMods
can't take a Timeline picture's slot.

Uploaded files remain in ComfyUI's `input/h3_pictures`, and uploading the same file again reuses it. Story exports
keep the file references, so moving a Timeline to another PC needs those files, as it does for wired pictures.
Timelines without pictures save and render exactly as before.

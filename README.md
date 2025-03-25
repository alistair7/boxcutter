# boxcutter
Utility for displaying and manipulating JPEG XL container files (ISO/IEC 18181-2).

This project will hopefully be made redundant by libjxl's planned
[`jxltran`](https://github.com/libjxl/libjxl/issues/871) utility.

While this is mainly intended for processing JPEG XL files, it can also deal with other
"ISO-BMFF-like" formats that use the 4CC box structure, whether or not they strictly
conform to ISO/IEC 14496-12.  e.g., MP4, HEIF (HEIC, AVIF), JPEG2000.

### General Features
- Display information about the boxes (type, offset, length) that compose the file.
- Append or insert additional boxes with a specified type and content.
- Remove specified boxes (not yet implemented).
- Export boxes - as full boxes including headers, or just the payload (not yet
  implemented).

The *content* of boxes is treated as opaque data, with some very limited exceptions.

boxcutter's input and output is always streamed, so it can deal with enormous files (and
enormous individual boxes) using very little memory, and it can be used effectively as
part of a pipeline.

### JPEG-XL-specific Features
A JPEG XL file can be a "raw" codestream, or stored in a container format allowing extra
information such as metadata to be included.

boxcutter can:

- Extract the raw JXL codestream from a container.
- Wrap a raw JXL codestream in the container format.
- Generate certain optional boxes that are meaningful to JPEG XL decoders (`jxll`).
- Identify JXLs that contain JPEG reconstruction data (via `count --type=jbrd`).

It CANNOT decode the JXL codestream, so it can't read or modify any properties of the
image (pixels, dimensions, depth, channels, frames, color space).

It CANNOT encode or decode the content of Brotli-compressed (`brob`) boxes, beyond
identifying the type of the compressed box.


### Modes

#### `list`
Displays the list of boxes that make up the file(s).

```
$ boxcutter.py list file1.jxl file2.mp4

file1.jxl:
seq off        len type
-----------------------
[0] 0x000       12 JXL 
[1] 0x00c       20 ftyp
[2] 0x020      269 jxlp
[3] 0x12d      146 brob : Compressed Exif box.
[4] 0x1bf      696 brob : Compressed xml  box.
[5] 0x477  2117651 jxlp

file2.mp4:
seq off          len type
-------------------------
[0] 0x0000        24 ftyp
[1] 0x0018     63241 moov
[2] 0xf721  27324296 mdat
```

`seq` is the position of the box in the file, numbered from zero.

`off` is the offset of the box from the start of the file, in (hexadecimal) bytes.  The
first offset is always 0.

`len` is the size of the box in (decimal) bytes, including its header.  A '+' prefix on
the last box's `len` means the length field in its header is set to 0, and the displayed
length is implied by the number of bytes remaining in the file.

`type` is a 4-character printable ASCII string (4CC) identifying the box type.

#### `count`
Prints the total number of boxes in the file, or the number of boxes of a specified type:

```
$ boxcutter.py count file.jxl
6

$ boxcutter.py count --type=brob file.jxl
2
```


#### `extract-jxl-codestream`
Converts a JXL container to a raw JXL codestream.

```
$ boxcutter.py extract-jxl-codestream < container.jxl > raw.jxl

$ jxlinfo container.jxl

JPEG XL file format container (ISO/IEC 18181-2)
JPEG XL image, 2800x3270, (possibly) lossless, 8-bit RGB
Color space: 672-byte ICC profile, CMM type: "lcms", color space: "RGB ", rendering intent: 0
Brotli-compressed Exif metadata: 146 compressed bytes
Brotli-compressed xml  metadata: 696 compressed bytes

$ jxlinfo raw.jxl

JPEG XL image, 2800x3270, (possibly) lossless, 8-bit RGB
Color space: 672-byte ICC profile, CMM type: "lcms", color space: "RGB ", rendering intent: 0
```

#### `wrap-jxl-codestream`
Converts a raw JXL codestream to a JXL in container format.

```
$ boxcutter.py wrap-jxl-codestream < raw.jxl > container.jxl

$ jxlinfo raw.jxl

JPEG XL image, 2800x3270, (possibly) lossless, 8-bit RGB
Color space: 672-byte ICC profile, CMM type: "lcms", color space: "RGB ", rendering intent: 0

$ jxlinfo container.jxl

JPEG XL file format container (ISO/IEC 18181-2)
JPEG XL image, 2800x3270, (possibly) lossless, 8-bit RGB
Color space: 672-byte ICC profile, CMM type: "lcms", color space: "RGB ", rendering intent: 0

$ boxcutter.py list container.jxl

seq off       len type
----------------------
[0] 0x000      12 JXL 
[1] 0x00c      20 ftyp
[2] 0x020 2117904 jxlc
```

By default the codestream is put into a single `jxlc` box, but this can be overridden
using the `--splits` option.  You can also add a `jxll` box to declare the JXL
conformance level:

```
$ boxcutter.py wrap-jxl-codestream --level=10 --splits=1024 < raw.jxl > container.jxl

$ boxcutter.py list container.jxl

seq off       len type
----------------------
[0] 0x000      12 JXL 
[1] 0x00c      20 ftyp
[2] 0x020       9 jxll : JPEG XL conformance level 10.
[3] 0x029    1036 jxlp
[4] 0x435 2116884 jxlp
```

You can split the codestream into any number of parts using `--splits` by passing multiple
byte offsets separated by commas.  You can also waste bytes in whimsical ways such as
putting the entire codestream into a single `jxlp` box (pass an empty string), or creating
any number of completely empty `jxlp` boxes (pass the same offset multiple times).

Note that splitting the codestream is pointless unless you're going to add boxes in
between the `jxlp`s.  The libjxl encoder splits the codestream so that basic information
about the JXL image - and possibly sufficient data to display a low-quality preview -
precedes any metadata such as Exif or XMP, while still keeping that metadata close to the
start of the file.  Unlike libjxl, we have no way of identifying the appropriate split
point!

#### `add`
Adds arbitrary boxes to an existing file.  `--box` can be passed any number of times, and
each one creates a box with the specified name and content.

The argument to `--box` is a string in one of two formats:

- `«TYPE»=«DATA»` creates a box of type `«TYPE»` with its content set to the string
  `«DATA»`.  By default the string gets encoded as UTF-8, but this can be overridden with
  the `--encoding` option.

- `«TYPE»@«FILENAME»` creates a box of type `«TYPE»` with its content read from the
  existing file named `«FILENAME»`.  `«FILENAME»` may be `-` to read data from stdin
  (unless stdin is already being used to read another box or the main input file).

```
$ boxcutter.py list oldfile.bin

seq off        len type
-----------------------
[0] 0x000       12 JXL 
[1] 0x00c       20 ftyp
[2] 0x020      269 jxlp
[3] 0x12d      146 brob : Compressed Exif box.
[4] 0x1bf      696 brob : Compressed xml  box.
[5] 0x477  2117651 jxlp

$ boxcutter.py add --box 'abcd=hello' --box 'xml @some/file.xmp' < oldfile.bin > newfile.bin

$ boxcutter.py list newfile.bin

seq off           len type
--------------------------
[0] 0x000000       12 JXL 
[1] 0x00000c       20 ftyp
[2] 0x000020      269 jxlp
[3] 0x00012d      146 brob : Compressed Exif box.
[4] 0x0001bf      696 brob : Compressed xml  box.
[5] 0x000477  2117651 jxlp
[6] 0x20548a       13 abcd
[7] 0x205497    40147 xml 
```

By default, new boxes are added to the end of the file.  `--at` can be used to specify an
index at which to insert them.  Valid indexes range from 0 (to prepend the boxes) to the
current number of boxes (to append the boxes, equivalent to passing -1 or leaving `--at`
unspecified).

`--at` can only be used once per command, so there's no way to add boxes at multiple
different positions in one go, but it's relatively efficient to pipe the output of one
instance of boxcutter into another:

```
$ boxcutter.py add --at 0 --box frst= < oldfile.bin | \
  boxcutter.py add --at 4 --box midl= | \
  boxcutter.py add --box last= > newfile.bin
  
seq off           len type
--------------------------
[0] 0x000000        8 frst
[1] 0x000008       12 JXL 
[2] 0x000014       20 ftyp
[3] 0x000028      269 jxlp
[4] 0x000135        8 midl
[5] 0x00013d      146 brob : Compressed Exif box.
[6] 0x0001cf      696 brob : Compressed xml  box.
[7] 0x000487  2117651 jxlp
[8] 0x20549a        8 last
```

Since an empty file is valid input, Add mode can be used to create ISO-BMFF-like files
from scratch:

```
$ boxcutter.py add --box 'abcd=hello' < /dev/null > newfile.bin

$ boxcutter.py list newfile.bin

seq off    len type
-------------------
[0] 0x000   13 abcd
```

### Implicit box size problems
The header of the last box in a file can have its size field set to 0, which means the
box extends to the end of the file, so the size is implicit.  In most cases this is fine,
but it makes certain operations difficult when both the input and output files aren't
seekable or stat-able (like if they are both pipes).

For example, appending boxes to a file whose current last box has its size field set
to 0 requires us to find out the real size of that box and set it in the header.  To find
out its size, we either need to examine the input file size to see how many bytes are
left, or write a placeholder for the size and seek back to correct it after writing the
rest of the box.  (Or buffer the whole box in memory, but boxcutter never does that.)  If
neither of those is possible, boxcutter will exit with an error.

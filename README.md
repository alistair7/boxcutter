# boxcutter
Utility for displaying and manipulating JPEG XL container files (ISO/IEC 18181-2).

This project will hopefully be made redundant by libjxl's planned
[`jxltran`](https://github.com/libjxl/libjxl/issues/871) utility.

While this is mainly intended for processing JPEG XL files, it can also deal with other
"ISO-BMFF-like" formats that use the 4CC box structure, whether or not they strictly
conform to ISO/IEC 14496-12.  e.g., MP4, HEIF (HEIC, AVIF), JPEG2000.

### General Features
- Display information about the boxes (type, offset, length) that compose the file
  (`list`).
- Append or insert additional boxes with a specified type and content (`add`).
- Remove specified boxes (`filter`).
- Export boxes - as full boxes including headers (`filter`), or just the payload
  (`extract`).

The *content* of boxes is treated as opaque data, with some very limited exceptions.

boxcutter's input and output is always streamed, so it can deal with enormous files (and
enormous individual boxes) using very little memory, and it can be used effectively as
part of a pipeline.

All commands that consume a single input file and produce a single output file accept
two positional arguments for the input and output file names.  If these are omitted or
set to '-', standard input and standard output are used.

### JPEG-XL-specific Features
A JPEG XL file can be a "raw" codestream, or stored in a container format allowing extra
information such as metadata to be included.

boxcutter can:

- Extract the raw JXL codestream from a container (`extract-jxl-codestream`).
- Wrap a raw JXL codestream in the container format (`wrap-jxl-codestream`).
- Generate certain optional boxes that are meaningful to JPEG XL decoders (specifically,
  `jxll`).
- Identify JXLs that contain JPEG reconstruction data (via `has --select=TYPE=jbrd`).

It CANNOT decode the JXL codestream, so it can't read or modify any properties of the
image (pixels, dimensions, depth, channels, frames, color space).

### Installation
No installation is needed.  Just download and run boxcutter.py.

boxcutter has an optional dependency on the [Brotli](https://pypi.org/project/Brotli/)
Python package from Google.  This allows it to compress and decompress `brob` boxes:

`python3 -m pip install brotli`

Everything else will work fine without Brotli - just some options related to `brob`
handling will be disabled.

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
Prints the total number of boxes in the file.  If one or more box specifiers are given
(see Box Specifiers below), only boxes that match ANY of these specifiers are counted.

Usage:

```
boxcutter.py count [-s BOXSPEC] [-v] [files ...]

options:
  -s BOXSPEC, --select BOXSPEC
                        Count only boxes that match the given specifier. May be used multiple times to include more boxes in the count.
  -v, --verbose         Always print the filenames followed by the number of boxes counted.

```

Example:

```
$ boxcutter.py count file.jxl
6

$ boxcutter.py count -v --select=TYPE=brob file.jxl
file.jxl: 2
```

#### `has`
This mode is a streamlined version of `count`, which just tells you whether or not a
matching box exists.  If a matching box exists in ALL input files, the exit status is 0;
otherwise it's non-zero.

Supported options are identical to `count`.

#### `extract`
Extracts the payload of a single box.  You must pass at least one box specifier (see Box
Specifiers below).  The *first box* that matches any of the specifiers is chosen, and its
payload is written to the output.

Usage:

```
boxcutter.py extract [-s BOXSPEC] [-d] [-D SIZE] [infile] [outfile]

options:
  -s BOXSPEC, --select BOXSPEC
                        Box specifier. May be given multiple times. The first box that matches any specifier is extracted.
  -d, --decompress      Decompress `brob` boxes when extracting, outputting the payload of the inner box.
  -D SIZE, --decompress-max SIZE
                        Abort if the box decompresses to more than SIZE bytes. SI and IEC suffixes are allowed. The default is 1GB. Use -1 for no maximum.
```

The `--decompress` options are only available if the `brotli` package is installed.

***DoS Warning***
The Python API for the latest release of `brotli` at the time of writing (v1.1.0) doesn't
allow callers to limit the length of decompressed data produced from a given chunk
of compressed input, so it may be possible for a malicious file to cause arbitrarily large
memory allocations.  This has been addressed in the development version of `brotli`, but
as yet it's unreleased.  Decompress untrusted boxes at your own risk.

The SIZE argument to `--decompress-max` understands SI (k, M, G, T) and IEC (Ki, Mi, Gi,
Ti) suffixes.  The suffix is not case sensitive, and in all cases a trailing 'b' is
allowed and ignored.  This protects against excessive disk usage, but not excessive memory
usage inside brotli.

Example:

```
$ boxcutter.py extract --select 'type=xml ' < in.jxl > out.xml
```

Note that `brob` compressed boxes may be matched based on their inner type, and output
as compressed Brotli blobs.  See `type` vs. `TYPE` in the Box Specifiers section.

If no matching box is found, or no box specifier is given, boxcutter exits with an error.

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

Usage:

```
boxcutter.py wrap-jxl-codestream [--level N] [--splits OFFSET,OFFSET,...] [infile] [outfile]

options:
  --level N, -l N       Add a codestream level declaration to the file, for level N (adds a `jxll` box to the output).
  --splits OFFSET,OFFSET,..., -s OFFSET,OFFSET,...
                        Write several `jxlp` boxes instead of a single `jxlc` box, splitting the codestream at these byte offsets.
```

Example:

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

Usage:

```
boxcutter.py add [--at AT] [--box BOX] [--encoding ENCODING] [infile] [outfile]

options:
  --at AT              Position to insert the boxes. Valid indexes range from 0 to the current box count. Default is -1, which appends the new boxes.
  --box BOX            Box specifier in the format "TYPE=DATA" (to create a box of type TYPE with content DATA) or "TYPE@FILE" (to set the box content from a file named FILE. FILE may be '-' to read box content from stdin. Boxes are added in the order they are
                       passed.
  --encoding ENCODING  When setting box content from the command line (TYPE=...), encode the text value using this character encoding. Default is UTF-8.
```

Example:

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

#### `filter`
This mode is for removing or modifying existing boxes.  You can either specify which
boxes to keep (`--keep`), or which boxes to remove (`--drop`).  These options both accept
a box specifier (see Box Specifiers below).  Either can be used multiple times in a
command, but they can't be mixed.

Usage:

```
boxcutter.py filter [--drop BOXSPEC | --keep BOXSPEC] [infile] [outfile]

options:
  --drop BOXSPEC  Remove the specified box(es).
  --keep BOXSPEC  Keep only the specified box(es).
```

Other than printing warnings in certain cases, `filter` mode makes no attempt to stop you
creating invalid JPEG XL files, which is easy to do by removing critical boxes.

There are several examples of how `filter` is used in the Box Specifiers section.

### Box Specifiers
Several commands accept "box specifiers" which are very basic expressions that identify a
(possibly empty) subset of the boxes in a file.

The syntax doesn't support complex expressions - you can only test one property per box
specifier.  Generally, you can pass multiple box specifiers, and they are implicitly
OR-ed together, so the set of boxes that match is the union of the sets matched by each
specifier.

#### Specifying boxes by index (`i`)
Specific indexes and (inclusive) ranges of indexes can be selected using the `i` property.
The first box is index 0.  If either end of a range is omitted, the range is unbounded in
that direction.

```
# Remove the first box
$ boxcutter.py filter --drop i=0 in.jxl > out.jxl

# Remove the first three boxes
$ boxcutter.py filter --drop i=0..2 in.jxl > out.jxl

# Remove the first three boxes and everything after the fourth box
$ boxcutter.py filter --drop i=0..2 --drop i=4.. in.jxl > out.jxl
# (This is just a confusing way to write `--drop i=3`.)
```

#### Specifying boxes by type (`type`, `itype`)
Specific box types can be selected using the `type` property (and its variations):

```
# Remove all Exif boxes
$ boxcutter.py filter --drop type=Exif in.jxl > out.jxl
```

By default, `brob` (brotli compressed) boxes are treated as being the type they *contain*
rather than all being `brob` type.  The command above would remove both plain `Exif` boxes
and `brob` boxes containing `Exif`.  Hence `type=brob` will never match anything (unless
you have a `brob` inside a `brob`).  To disable this special treatment of `brob` boxes,
put `TYPE` in upper case:

```
# Remove all Exif boxes (but not brob boxes containing Exif)
$ boxcutter.py filter --drop TYPE=Exif in.jxl > out.jxl

# Remove all brob-compressed boxes, ignoring their content
$ boxcutter.py filter --drop TYPE=brob in.jxl > out.jxl
```

To make the match case-insensitive, use `itype` (or `ITYPE` if you don't want to look
inside `brob`s).

```
# Remove all exif, Exif, eXif, ..., EXIF.
$ boxcutter.py filter --drop itype=exif in.jxl > out.jxl
```

For both `type` and `itype`, wildcard matching is supported.  This is enabled when you
use `~=` instead of `=`.  Basic globbing patterns are supported: '\*' matches zero or more
characters, '?' matches exactly 1 character, and a set of characters enclosed in '[]'
matches any single character from that set.  To include a literal '\*', '?' or '[' in the
pattern, enclose it in square brackets, as a set of one possible character.

In most shells it will be necessary to quote the argument if these globbing characters
are used, to avoid the shell itself trying to interpret them.

```
# Remove all boxes starting with jxl (case insensitive)
$ boxcutter.py filter --drop 'itype~=jxl*' in.jxl > out.jxl
```

#### Convenience filters
The special box specifier, `@jxl`, matches a minimal set of reserved JPEG XL boxes,
equivalent to specifying `itype~=jxl*` and `type=ftyp`.  This does not include `jbrd`,
`Exif`, `'xml '`, or `jumb`.

The special box specifier, `@JXL` is equivalent to specifying `@jxl`, `type=jbrd`,
`type=Exif`, `type='xml '`, and `type=jumb`.  i.e., it's a superset of `@jxl` that
includes box types that could be needed for JPEG reconstruction.

There is unfortunately no automatic way to "only include `Exif` and `xml ` if required for
JPEG reconstruction", because the input is streamed, and boxcutter may encounter one of
these box types before it knows whether a `jbrd` box is present.  A clumsy workaround
for this is:

```bash
if boxcutter.py has -sTYPE=jbrd in.jxl; then
  boxspec=@JXL
else
  boxspec=@jxl
fi
boxcutter.py filter --keep="$boxspec" in.jxl out.jxl
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

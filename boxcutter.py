#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) Alistair Barrow. All rights reserved.
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file.

import collections
import fnmatch
import io
import math
import os
import shlex
import stat
import struct
import sys
import uuid

try:
  import brotli
  HAVE_BROTLI = True
except ImportError:
  HAVE_BROTLI = False

IO_BLOCK_SIZE = 16384
JXL_CONTAINER_SIG = b'\0\0\0\x0cJXL \r\n\x87\n'

# Boxes bigger than this require extended box size
BIG_SIZE = 0xFFFFFFFF

def main(argv):
  import argparse
  parser = argparse.ArgumentParser()
  subparsers = parser.add_subparsers(dest='mode', metavar='MODE')

  inOutParser = argparse.ArgumentParser(add_help=False)
  inOutParser.add_argument('infile', nargs='?', default='-',
                           help='Input file.  May be `-` to read from stdin.  Default is `-`.')
  inOutParser.add_argument('outfile', nargs='?', default='-',
                           help='Output file.  May be `-` to write to stdout.  Default is `-`.')

  listParser = subparsers.add_parser('list', help='List all boxes in the named files.')
  listParser.add_argument('files', nargs='*')

  countSelectParser = argparse.ArgumentParser(add_help=False)
  countSelectParser.add_argument('-s', '--select', metavar='BOXSPEC', action='append',
                                 help='Count only boxes that match the given specifier.' \
                                 '  May be used multiple times to include more boxes in ' \
                                 'the count.')
  countSelectParser.add_argument('-v', '--verbose', action='store_true', help='Always print the filenames followed by the number of boxes counted.')
  countSelectParser.add_argument('files', nargs='*')

  countParser = subparsers.add_parser('count', parents=[countSelectParser],
                                      help='Count boxes.')
  countParser.add_argument('-t', '--type', dest='boxtype', help=argparse.SUPPRESS)

  hasParser = subparsers.add_parser('has', parents=[countSelectParser],
                                    help='Check for existence of boxes.')

  extractParser = subparsers.add_parser('extract', parents=[inOutParser],
                                        help='Extract the payload of the first matching box.')
  extractParser.add_argument('-s', '--select', metavar='BOXSPEC', action='append', help='Box specifier.  May be given multiple times.  The first box that matches any specifier is extracted.')
  extractParser.add_argument('-d', '--decompress', action='store_true',
                             help='Decompress `brob` boxes when extracting, outputting ' \
                                  'the payload of the inner box.' \
                                  if HAVE_BROTLI else argparse.SUPPRESS)
  extractParser.add_argument('-D', '--decompress-max', metavar='SIZE', default=None,
                             help='Abort if the box decompresses to more than SIZE ' \
                                  'bytes.  SI and IEC suffixes are allowed.  The ' \
                                  'default is 1GB.  Use -1 for no maximum.' \
                                  if HAVE_BROTLI else argparse.SUPPRESS)

  extractJxlParser = subparsers.add_parser('extract-jxl-codestream', parents=[inOutParser],
                                           help='Extract the raw JPEG XL codestream from a JXL container file.')

  wrapJxlParser = subparsers.add_parser('wrap-jxl-codestream', parents=[inOutParser],
                                        help='Wrap a raw JPEG XL codestream in a simple ISO/IEC 18181-2 "BMFF-like" container.')
  wrapJxlParser.add_argument('--level', '-l', type=int, metavar='N', help='Add a codestream level declaration to the file, for level N (adds a `jxll` box to the output).')
  wrapJxlParser.add_argument('--splits', '-s', metavar='OFFSET,OFFSET,...', help='Write several `jxlp` boxes instead of a single `jxlc` box, splitting the codestream at these byte offsets.')

  addParser = subparsers.add_parser('add', parents=[inOutParser],
                                    help='Add one or more metadata boxes to the file.')
  addParser.add_argument('--at', default=-1, type=int, help='Position to insert the boxes.  Valid indexes range from 0 to the current box count.  Default is -1, which appends the new boxes.')
  addParser.add_argument('--box', action='append',
                         help='Box description in the format "TYPE=DATA" ' \
                              '(to create a box of type TYPE with content DATA) or ' \
                              '"TYPE@FILE" (to set the box content from a file named ' \
                              'FILE.  FILE may be \'-\' to read box content from stdin.' \
                              '  Boxes are added in the order they are passed.')
  addParser.add_argument('--encoding', default='UTF-8', help='When setting box content from the command line (TYPE=...), encode the text value using this character encoding.  Default is UTF-8.')

  filterParser = subparsers.add_parser('filter', parents=[inOutParser],
                                       help='Remove or modify boxes.')
  dropOrKeep = filterParser.add_mutually_exclusive_group()
  dropOrKeep.add_argument('--drop', metavar='BOXSPEC', action='append', help='Remove the specified box(es).')
  dropOrKeep.add_argument('--keep', metavar='BOXSPEC', action='append', help='Keep only the specified box(es).')

  args = parser.parse_args(argv[1:])

  if args.mode == 'list':
    return doList(args.files)
  elif args.mode == 'has' or args.mode == 'count':
    if args.mode == 'count' and args.boxtype is not None:
      if args.select is None:
        args.select = []
      args.select.append(f'TYPE={args.boxtype}')
    return doCount(args.files, args.select, args.mode == 'has', verbose=args.verbose)
  elif args.mode in ('extract', 'extract-jxl-codestream', 'wrap-jxl-codestream', 'add', 'filter'):
    with openFileOrStdin(args.infile, 'rb') as infile, \
         openFileOrStdout(args.outfile, 'wb') as outfile:
      if args.mode == 'extract':
        decompressMax = 0
        if args.decompress:
          decompressMax = 1_000_000_000 if args.decompress_max is None \
                                        else decodeSize(args.decompress_max)
        return doExtractBox(infile, outfile, args.select, decompressMax)
      if args.mode == 'extract-jxl-codestream':
        return extractJxlCodestream(infile, outfile)
      if args.mode == 'wrap-jxl-codestream':
        splits = map(int, args.splits.split(',')) if args.splits else [] if args.splits is not None else None
        return addContainer(infile, outfile, jxll = args.level, splits=splits)
      if args.mode == 'add':
        return doAddBoxes(infile, outfile, args.box, args.encoding, args.at)
      else: # mode == 'filter'
        return doFilter(infile, outfile, args.keep is not None,
                        args.keep if args.keep is not None else args.drop)

  return 0


def doList(filenames):
  multipleFiles = len(filenames) > 1
  usedStdin = False
  for fi,filename in enumerate(filenames):
    if filename == '-':
      if usedStdin:
        sys.stderr.write('stdin can only be read once.\n')
        if fi < len(filenames) - 1: sys.stderr.write('\n')
        continue
      usedStdin = True

    zeroLengthLastBox = False

    with openFileOrStdin(filename, 'rb') as f:
      # Iterate through boxes in the file, saving metadata and any interesting details.
      try:
        boxList = []
        details = {}
        invalid = 'invalid?'
        with BoxReader(f) as reader:
          for i,box in enumerate(reader):
            boxList.append(box)

            if box.boxtype == b'brob':
              contentStart = reader.readCurrentBoxPayload(4)
              if len(contentStart) == 4:
                details[i] = f'Compressed {contentStart.decode("ascii", errors="replace")} box.'
              else:
                details[i] = invalid

            elif box.boxtype == b'Exif':
              tiffOffsetBytes = reader.readCurrentBoxPayload(4)
              if len(tiffOffsetBytes) != 4:
                details[i] = invalid
                continue
              (tiffOffset,) = struct.unpack('>I', tiffOffsetBytes)
              moved = reader.seekCurrentBoxPayload(tiffOffset)
              if moved != tiffOffset:
                details[i] = f'TIFF offset is invalid ({tiffOffset}).'
                continue
              tiffHeader = reader.readCurrentBoxPayload(4)
              if tiffHeader not in (b'II\x2A\0', b'MM\0\x2A'):
                details[i] = f'TIFF header at 0x{tiffOffset:x} is invalid.'
                continue
              details[i] = f'{"Big" if tiffHeader[0:1] == b"M" else "Little"}-endian TIFF header at 0x{tiffOffset:x}.'

            elif box.boxtype == b'jbrd':
              details[i] = 'JPEG reconstruction data.'

            elif box.boxtype == b'jxll':
              levelByte = reader.readCurrentBoxPayload(1)
              details[i] = 'invalid?' if len(levelByte) != 1 else \
                           f'JPEG XL conformance level {levelByte[0]}.'

            elif box.boxtype == b'uuid':
              uuidBytes = reader.readCurrentBoxPayload(16)
              if len(uuidBytes) == 16:
                details[i] = str(uuid.UUID(bytes=uuidBytes))
              else:
                details[i] = invalid

          if boxList[-1].length == 0:
            zeroLengthLastBox = True
            boxList[-1].length = reader.finalBoxSize()

      except RawJxlError:
        sys.stdout.write(f'{shlex.quote(filename)}: Raw JXL codestream - not a container.\n')
        if fi < len(filenames) - 1: sys.stdout.write('\n')
        continue
      except Exception as ex:
        sys.stderr.write(f'{shlex.quote(filename)}: Failed to parse as ISO BMFF format; {ex}.\n')
        if fi < len(filenames) - 1: sys.stderr.write('\n')
        continue

    if len(boxList) == 0:
      sys.stdout.write(f'{shlex.quote(filename)}: Empty file.\n')
      if fi < len(filenames) - 1: sys.stdout.write('\n')
      continue

    largestOffset = 0x100 # Force minimum 3 digits so the "0x" and headings always fit
    largestLength = 100
    boxData = []
    for box in boxList:
      if box.offset > largestOffset: largestOffset = box.offset
      if box.length > largestLength: largestLength = box.length

    indexWidth = math.floor(math.log10(len(boxList))) + 1;
    offsetWidth = math.floor(math.log(largestOffset, 16)) + 1;
    lengthWidth = math.floor(math.log10(largestLength)) + 2;

    if multipleFiles:
      sys.stdout.write(f'{shlex.quote(filename)}:\n')
    headings = f'seq{" "*indexWidth}{"off":<{offsetWidth}}   {"len":>{lengthWidth}} type\n'
    sys.stdout.write(headings)
    sys.stdout.write('-' * (len(headings)-1) + '\n')
    unnecessary = False
    for i,box in enumerate(boxList):
      hasImplicitLength = (i == len(boxList) - 1) and zeroLengthLastBox
      sys.stdout.write(f'[{i:0{indexWidth}d}] 0x{box.offset:0{offsetWidth}x} ')
      if hasImplicitLength:
        sys.stdout.write(f'{box.length:+{lengthWidth}d}')
      else:
        sys.stdout.write(f'{box.length:{lengthWidth}d}')
      sys.stdout.write(f' {box.boxtype.decode("ascii", errors="replace")}')
      detail = details.get(i)
      if detail:
        sys.stdout.write(f' : {detail}')
      if box.hasExtendedSize and (box.length <= BIG_SIZE or hasImplicitLength):
        sys.stdout.write(' *')
        unnecessary = True
      sys.stdout.write('\n')
    if unnecessary:
      sys.stdout.write('\n  *Unnecessary use of extended box size wastes 8 bytes.\n')
    if fi < len(filenames) - 1: sys.stdout.write('\n')
  return 0


def doCount(filenames, boxspecStrings, justCheck, verbose=False, out=sys.stdout):
  """
  Count matching boxes in the given files.

  @param[in] filenames List of files to read.
  @param[in] boxspecStrings Iterable of box specifiers to include in the count.  @c None
                            to match all boxes. An empty iterable maches no boxes.
  @param[in] verbose If False, and @p justCheck is True, don't produce any output.
                     If False, and @p justCheck is False, and a single file is given,
                     output only the number of matching boxes.
                     Else output each quoted filename followed by the number of matching
                     boxes counted in that file (which is never > 1 if @p justCheck is
                     True).

  @return 0 if @p justCheck is True and ALL files contain at least one matching box.
  @return 0 if @p justCheck is False and the boxes were counted successfully (even if
            no matches were found).
  @return 1 otherwise.
  """
  multipleFiles = len(filenames) > 1
  mode = MODE_HAS if justCheck else MODE_COUNT
  try:
    boxspecs = boxspecStringsToBoxspecList(boxspecStrings)
  except InvalidBoxSpec as ex:
    sys.stderr.write(f'{ex}\n')
    return 1

  usedStdin = False
  retval = 0

  for i,filename in enumerate(filenames):
    if filename == '-':
      if usedStdin:
        sys.stderr.write('stdin can only be read once.\n')
        if justCheck:
          return 1
        if i < len(filenames) - 1: sys.stderr.write('\n')
        continue
      usedStdin = True

    with openFileOrStdin(filename, 'rb') as src:
      count = scanBoxes(src, dst=None, mode=mode, boxspecs=boxspecs)
    if count < 0:
      if count == RAW_JXL:
        sys.stderr.write(f'{shlex.quote(filename)}: Raw JXL codestream - not a container.\n')
      else:
        sys.stderr.write(f'{shlex.quote(filename)}: Failed to parse as ISO BMFF format.\n')
      if justCheck and not verbose: return 1
      retval = 1
      continue

    if verbose or multipleFiles:
      out.write(f'{shlex.quote(filename)}: ')
    if verbose or not justCheck:
      out.write(str(count))
      out.write('\n')
    if justCheck and count == 0:
      if not verbose: return 1
      retval = 1

  return retval



def extractJxlCodestream(src, dst):

  jxlBox = src.read(len(JXL_CONTAINER_SIG))
  if jxlBox != JXL_CONTAINER_SIG:
    sys.stderr.write('Input file is not a JPEG XL container.\n')
    return 1

  seenJxlc = False
  seenJbrd = False
  nextJxlp = 0

  with CatReader(False, jxlBox, src) as src, BoxReader(src) as reader:
    for box in reader:
      if box.boxtype == b'jxlc':
        if seenJxlc or nextJxlp != 0:
          raise InvalidJxlContainerError('Multiple `jxlc` boxes in input.')
        seenJxlc = True
        reader.copyCurrentBoxPayload(dst)
        continue

      if box.boxtype == b'jxlp':
        if seenJxlc or nextJxlp < 0:
          raise InvalidJxlContainerError('Unexpected `jxlp` box.')

        # Each jxlp starts with an int32be sequence number starting at 0.
        # For the last jxlp box, the sequence number also has the most significant bit set.
        seqNumBytes = reader.readCurrentBoxPayload(4)
        if len(seqNumBytes) != 4:
          raise InvalidJxlContainerError(f'Invalid length for jxlp box.')
        (seqNum,) = struct.unpack('>I', seqNumBytes)
        isLastJxlp = (seqNum & 0x80000000) != 0
        if isLastJxlp:
          seqNum &= 0x7FFFFFFF
        if seqNum != nextJxlp:
          sys.stderr.write(f'jxlp box out of sequence: expected {nextJxlp}; got {seqNum}{" (last)" if isLastJxlp else ""}')
          return 2
        nextJxlp = -1 if isLastJxlp else (nextJxlp + 1)
        done = reader.copyCurrentBoxPayload(dst)
        continue;

      if not seenJbrd and box.boxtype == b'jbrd':
        sys.stderr.write('Warning: input contains JPEG reconstruction data.\n')
        sys.stderr.write('It will not be possible to losslessly reconstruct a JPEG from the raw codestream.\n')
        seenJbrd = True

      elif box.boxtype == b'jxll':
        levelByte = reader.readCurrentBoxPayload(1)
        if len(levelByte) != 1:
          return 2
        if levelByte[0] > 5:
          sys.stderr.write(f'Warning: the input declares a level {levelByte[0]} codestream.\n')
          sys.stderr.write(f'A raw codestream should not use features that require level > 5.\n')


  if nextJxlp > 0:
    sys.stderr.write(f'Warning: the last jxlp box was not marked as being the last jxlp box.\n')

  return 0 if (seenJxlc or nextJxlp != 0) else 1


def doExtractBox(src, dst, boxspecStrings, decompressMax=0):
  if len(boxspecStrings) == 0:
    sys.stderr.write('You must specify which box to extract using --select.\n')
    return 2
  if decompressMax != 0 and not HAVE_BROTLI:
    sys.stderr.write('Cannot decompress boxes without the `brotli` package.')
    return 2
  retval = doScanBoxes(src, dst, MODE_EXTRACT_FIRST, boxspecStrings,
                       decompressMax=decompressMax)
  if retval == DECOMP_TOO_BIG:
    sys.stderr.write(f'Aborted because the box decompressed to over {decompressMax} ' \
                     'bytes.  Try passing a larger value to --decompress-max (-1 for no' \
                     ' limit).\n')
    return 2
  elif retval != 0:
    sys.stderr.write('Failed to extract any box.\n')
    return 2
  return 0

def decodeSize(sz):
  """
  Convert a @c str to an @c int, intepreting SI/IEC suffixes.

  Suffixes of k, m, g, and t are supported, for kilo-, mega-, giga-, and tera- and these
  multiply the numeric part by the corresponding power of 1000.  For 1024-based multiples,
  use ki, mi, gi, ti.  Not case sensitive.  Leading and trailing spaces are ignored, as
  are spaces between the digits and the suffix.  A 'b' following the suffix is allowed and
  ignored.

  e.g.
  "1"      -> 1
  "1K"     -> 1000
  "1 kb"   -> 1000
  "1Ki"    -> 1024
  " 1KiB " -> 1024

  For inputs consisting only of digits 0-9, this function is equivalent to @c int(sz).
  Raises ValueError if the format is incorrect.
  """
  import re
  match = re.match('^ *(-?[0-9]+) *([kmgt]i?)?b? *$', sz.lower())
  if not match:
    raise ValueError(f'Invalid size string "{sz}"')
  suffix = match.group(2)
  mult = 1000 if suffix == 'k'  else \
         1024 if suffix == 'ki' else \
         1000 * 1000 if suffix == 'm'  else \
         1024 * 1024 if suffix == 'mi' else \
         1000 * 1000 * 1000 if suffix == 'g'  else \
         1024 * 1024 * 1024 if suffix == 'gi' else \
         1000 * 1000 * 1000 * 1000 if suffix == 't'  else \
         1024 * 1024 * 1024 * 1024 if suffix == 'ti' else \
         1
  return mult * int(match.group(1))

def addContainer(src, dst, jxll=None, splits=None):
  """
  @param[in] splits If not None, this must be an iterable of ints giving byte offsets at
                    which the JXL codestream should be split.  If this is provided, the
                    output will use `len(splits)+1` `jxlp` boxes instead of a single
                    `jxlc` box.
  """
  codestreamBytesRemain = streamSize(src)
  jxlSig = src.read(2) # Effectively peeking, so don't decrement codestreamBytesRemain
  if jxlSig != b'\xff\n':
    if jxlSig == JXL_CONTAINER_SIG[:2] and src.read(len(JXL_CONTAINER_SIG)-2) == JXL_CONTAINER_SIG[2:]:
      sys.stderr.write('Input is already in a container.\n')
    return 1

  # Always start with 'JXL ' and 'ftyp'
  dst.write(JXL_CONTAINER_SIG)
  dst.write(b'\0\0\0\x14ftypjxl \0\0\0\0jxl ')
  if jxll is not None:
    dst.write(b'\0\0\0\x09jxll' + bytes([jxll]))

  with CatReader(False, jxlSig, src) as src:

    if splits is not None:
      sortedSplits = list(sorted(splits))
      lastOff = 0
      seqNum = -1
      for i,off in enumerate(sortedSplits):
        seqNum = i
        chunkSize = off - lastOff
        size = 12 + chunkSize
        if size > BIG_SIZE:
          extSize = size + 8
          size = 1
        else:
          extSize = 0
        lastOff = off

        dst.write(struct.pack('>I', size))
        dst.write(b'jxlp')
        if extSize > 0:
          dst.write(struct.pack('>Q', extSize))
        dst.write(struct.pack('>I', seqNum))
        codestreamBytesRemain -= copyData(src, dst, chunkSize)

      seqNum = (seqNum + 1) | 0x80000000

      payloadSize = (4 + codestreamBytesRemain) if codestreamBytesRemain >= 0 else -1
      lastBoxSize = writeBoxHeader(dst, b'jxlp', payloadSize) + \
                    dst.write(struct.pack('>I', seqNum)) + \
                    copyData(src, dst, None)
    else:
      lastBoxSize = writeBoxHeader(dst, b'jxlc', codestreamBytesRemain) + \
                    copyData(src, dst, None)

  # If the input wasn't seekable but the output is, we may now be able to set the last
  # box's size field.
  if codestreamBytesRemain < 0 and lastBoxSize <= BIG_SIZE and dst.seekable():
    fileEnd = dst.tell()
    dst.seek(-lastBoxSize, os.SEEK_CUR)
    dst.write(struct.pack('>I', lastBoxSize))
    dst.seek(fileEnd)
  return 0


def doAddBoxes(infile, outfile, newboxes, encoding, at=-1):
  stdinCount = sum(map(lambda x : 1 if (x[4:] == '@-') else 0, newboxes)) + \
               (1 if infile == sys.stdin.buffer else 0)
  if stdinCount > 1:
    sys.stderr.write('Error: stdin can only be used once in a single command.\n')
    return 1

  with BoxReader(infile) as reader:

    appendingBoxes = len(newboxes) > 0
    originalBytesCopied = 0
    i = -1

    for i,box in enumerate(reader):
      if i == at:
        # Insert the boxes here
        if _writeBoxes(outfile, newboxes, encoding, atEnd=False) == -1:
          return 1
        appendingBoxes = False

      # Copy the existing box.
      if box.length == 0:
        # Last box has its size field set to 0.  If we're appending boxes after this, we
        # must set the size explicitly, but even if we're not, try anyway.

        # If input size is known, we can work out how many bytes are left.
        fullInputSize = streamSize(infile)
        if fullInputSize != -1:
          payloadSize = fullInputSize - originalBytesCopied - (16 if box.hasExtendedSize else 8)
          originalBytesCopied += writeBoxHeader(outfile, box.boxtype, payloadSize)
          payloadWrote = reader.copyCurrentBoxPayload(outfile)
          originalBytesCopied += payloadWrote
          if payloadWrote != payloadSize:
            sys.stderr.write("Error: Failed to calculate size of the (former) last " \
                             f"box.  We expected it to be {payloadSize}, but we wrote " \
                             f"{payloadWrote}.\n")
            return 1
          break

        # If the output is seekable, set a placeholder and update the size later.
        if outfile.seekable():
          outBoxOffset = outfile.tell()
          reader.copyCurrentBox(outfile)
          boxEnd = outfile.tell()
          outfile.seek(outBoxOffset)
          newBoxSize = boxEnd - outBoxOffset
          if box.hasExtendedSize:
            # Unsure whether using an extended box size to store 0 is valid, but deal with it anyway.
            outfile.seek(outBoxOffset + 8)
            outfile.write(struct.pack('>Q', newBoxSize))
          else:
            if newBoxSize > BIG_SIZE:
              # TODO: Handle big boxes
              sys.stderr.write(f'Adding (final) boxes larger than 0x{BIG_SIZE:X} bytes is not supported yet.\n')
            outfile.write(struct.pack('>I', newBoxSize))
          outfile.seek(boxEnd)
          break

        # Otherwise we can't set an explicit size
        if appendingBoxes:
          sys.stderr.write("Error: either the input file or the output file must be " \
                           "seekable to set the (former) last box size correctly.\n")
          return 1

      # Copy the entire box
      originalBytesCopied += reader.copyCurrentBox(outfile)

    if at > i+1:
      sys.stderr.write(f"Error: can't insert boxes at position {at}; box count is {i+1}.\n")
      return 1

    if appendingBoxes and _writeBoxes(outfile, newboxes, encoding, atEnd=True) == -1:
      return 1
  return 0

def doFilter(src, dst, keep, boxspecStrings):
  return doScanBoxes(src, dst, MODE_KEEP if keep else MODE_DROP, boxspecStrings)

MODE_KEEP = 0
MODE_DROP = 1
MODE_EXTRACT_FIRST = 2
MODE_COUNT = 3
MODE_HAS = 4

RAW_JXL = -1
FAILED_PARSE = -2
DECOMP_TOO_BIG = -3

def boxspecStringsToBoxspecList(boxspecStrings):
  """
  Parse an iterable of boxspec strings and return a list of BoxSpec objects.
  Raises InvalidBoxSpec if any specifier isn't valid.
  """
  if boxspecStrings is None: return None
  boxspecs = []
  for s in boxspecStrings:
    if s in ('@jxl', '@JXL'):
      boxspecs += [BoxSpec('ITYPE~=jxl*'), BoxSpec('TYPE=ftyp')]
      if s == '@JXL':
        boxspecs += [BoxSpec('TYPE=jbrd'), BoxSpec('type=Exif'), BoxSpec('type=xml '),
                     BoxSpec('type=jumb')]
    else:
      boxspecs.append(BoxSpec(s))
  return boxspecs

def doScanBoxes(src, dst, mode, boxspecStrings, decompressMax=0):
  """
  Wrapper for @ref doScanBoxes that translates boxspec strings into objects.
  """
  return scanBoxes(src, dst, mode, boxspecStringsToBoxspecList(boxspecStrings),
                   decompressMax)

def scanBoxes(src, dst, mode, boxspecs, decompressMax=0):
  """
  Copy all or parts of @p src to @p dst, depending on @p mode and @p boxspecs.

  @param src Readable file-like object for the input.
  @param dst Writable file-like object for the result.  May be None for read-only modes.
  @param mode MODE_KEEP if @p boxspecs is defining a whitelist of boxes to keep.
              MODE_DROP if @p boxspecs is defining a blacklist of boxes to drop.
              MODE_EXTRACT_FIRST if @p boxspecs is just used to identify the first
                                 matching box.  Its payload will be the only thing output.
              MODE_COUNT to return the number of boxes that match any element of
                         @p boxspecs, or the total number of boxes if @p boxspecs is None.
              MODE_HAS is like MODE_COUNT, but stops after counting max 1 box.

  @param boxspecs List of BoxSpec objects determining which boxes are affected.
  @param[in] decompressMax (Only for MODE_EXTRACT_FIRST) If 0, do not decompress `brob`
                           boxes.  If > 0, decompress `brob` boxes but fail if any exceed
                           this number of decompressed bytes.  If < 0, decompress `brob`
                           boxes with no restriction on size.

  @return RAW_JXL if the input appears to be a raw codestream.
  @return DECOMP_TOO_BIG if the decompressed data from a box exceeded @p decompressMax.
  @return FAILED_PARSE if the input couldn't be parsed for some other reason.
  If mode is @c MODE_KEEP, @c MODE_DROP, or @c MODE_EXTRACT_FIRST, @return 0 on success,
  else 1.
  If mode is @c MODE_COUNT or @c MODE_HAS: @return the number of matching boxes (limited
  to 1 for MODE_HAS).
  """
  seen = collections.defaultdict(lambda : 0)
  matchCount = 0 # Only updated for MODE_COUNT

  try:
    with BoxReader(src) as reader:

      for i,box in enumerate(reader):
        innerType = box.boxtype
        boxStart = b''
        if box.boxtype == b'brob':
          # Read the inner type.  Don't use readCurrentBoxPayload, as we might want to copy
          # the header later.
          want = 20 if box.hasExtendedSize else 12
          boxStart = reader.readCurrentBox(want)
          innerType = boxStart[-4:]
          if len(boxStart) != want or not isValid4cc(innerType):
            raise InvalidBmffError(f"Invalid `brob` box at position {i}.")

        matches = boxspecs is None or any(
            map(lambda b : b.matches(i, box, innerType, seen[innerType]), boxspecs)
          )
        #sys.stderr.write(f'{box} {"matches" if matches else "does not match"}.\n')

        if mode == MODE_EXTRACT_FIRST and matches:
          # We have either read nothing, or we've read the header + 4 bytes
          if decompressMax != 0 and box.boxtype == b'brob':
            # TODO: make use of max_output_size after brotli version 1.1.0.
            decompSize = 0
            decompressor = brotli.Decompressor()
            while True:
              compBlock = reader.readCurrentBox(IO_BLOCK_SIZE)
              if len(compBlock) == 0: break
              decompBlock = decompressor.process(compBlock)
              decompSize += len(decompBlock) 
              if decompressMax > 0 and decompSize > decompressMax:
                return DECOMP_TOO_BIG
              dst.write(decompBlock)
            while not decompressor.is_finished():
              decompBlock = decompressor.process(b'')
              decompSize += len(decompBlock) 
              if decompressMax > 0 and decompSize > decompressMax:
                return DECOMP_TOO_BIG
              dst.write(decompBlock)
          else:
            if len(boxStart) > 0:
              dst.write(boxStart[-4:])
              reader.copyCurrentBox(dst)
            else:
              reader.copyCurrentBoxPayload(dst)
          return 0

        elif (mode == MODE_KEEP and matches) or (mode == MODE_DROP and not matches):
          dst.write(boxStart)
          reader.copyCurrentBox(dst)

        elif mode in (MODE_COUNT, MODE_HAS) and matches:
          if mode == MODE_HAS: return 1
          matchCount += 1

        seen[innerType] += 1

  except RawJxlError:
    return RAW_JXL
  except InvalidBmffError:
    return FAILED_PARSE

  return 1 if mode == MODE_EXTRACT_FIRST else \
         matchCount if mode == MODE_COUNT else \
         0


def _writeBoxes(outfile, boxes, encoding, atEnd):
  """
  Write boxes at the current position.

  @param outfile Open binary file.
  @param boxes List of box descriptor strings.
  @param encoding Character encoding to use if box content is directly specified as text.
  @param atEnd Should be True if these boxes are going to be at the end of the file, which
               gives us the option of not specifying the size of the last box.
  @return The number of bytes written, or -1 on error.
  """
  wrote = 0
  for boxi,newBox in enumerate(boxes):
    newTypeStr = newBox[:4]
    newTypeBytes = newTypeStr.encode('ASCII', errors='ignore')
    newMethod = newBox[4:5]
    newDataSource = newBox[5:]
    if len(newTypeStr) != 4 or not isValid4cc(newTypeBytes) or newMethod not in ('=','@'):
      sys.stderr.write(f'Invalid box specifier: {shlex.quote(newBox)}.\n')
      return -1

    if newMethod == '=':
      data = newDataSource.encode(encoding)
      wrote += writeBoxHeader(outfile, newTypeBytes, len(data)) + \
               outfile.write(data)
      continue

    with openFileOrStdin(newDataSource, 'rb') as inbox:
      dataSize = streamSize(inbox)

      if dataSize == -1:
        if (not atEnd or boxi != len(boxes)-1) and not outfile.seekable():
          sys.stderr.write("Error: output isn't seekable, and the box size can't be "
                           "determined in advance.\n")
          return -1
        if outfile.seekable():
          # Bookmark the size field so we can come back and update it later
          outBoxOffset = outfile.tell()

      wrote += writeBoxHeader(outfile, newTypeBytes, dataSize) + \
               copyData(inbox, outfile, dataSize)

      if dataSize == -1 and outfile.seekable():
        boxEnd = outfile.tell()
        outfile.seek(outBoxOffset)
        newBoxSize = boxEnd - outBoxOffset
        if newBoxSize > BIG_SIZE:
          # TODO: Handle big boxes
          sys.stderr.write(f'Adding boxes larger than 0x{BIG_SIZE:X} bytes is not supported yet.\n')
          return 1
        outfile.write(struct.pack('>I', newBoxSize))
        outfile.seek(boxEnd)
  return wrote


def writeBoxHeader(to, boxtype, payloadSize):
  """
  Write the header of a @p boxtype box to an open file, @p to.

  If payloadSize is < 0, the size field is set to zero.
  @return the number of bytes written (8 or 16, depending on the declared payload size).
  """
  if payloadSize < 0:
    # Only valid if this the last box
    return to.write(b'\0\0\0\0') + \
           to.write(boxtype)
  boxSize = 8 + payloadSize
  if boxSize <= BIG_SIZE:
    return to.write(struct.pack('>I', boxSize)) + \
           to.write(boxtype)
  boxSize += 8
  return to.write(b'\0\0\0\x01') + \
         to.write(boxtype) + \
         to.write(struct.pack('>Q', boxSize))

def isValid4cc(bytes4):
  return len(bytes4) == 4 and all(map(lambda b : (b >= 0x20 and b <= 0x7e), bytes4))
def isValidBoxType(str4):
  try:
    return isValid4cc(str4.encode('ASCII'))
  except UnicodeError:
    return False

def openFileOrStdin(name, *args, **kwargs):
  return (sys.stdin.buffer if name == '-' else open(name, *args, **kwargs))

def openFileOrStdout(name, *args, **kwargs):
  return (sys.stdout.buffer if name == '-' else open(name, *args, **kwargs))

def streamSize(f):
  """
  Return the full size in bytes of the open file, @p f, using fstat or seek/tell.
  If the file isn't seekable, return -1.
  """
  try:
    statInfo = os.fstat(f.fileno())
    if stat.S_ISREG(statInfo.st_mode):
      return statInfo.st_size
  except OSError:
    pass
  if not f.seekable(): return -1
  # Unlike C's ftell(), Python's tell() is safe to use as a byte offset for binary files.
  pos = f.tell()
  end = f.seek(0, io.SEEK_END)
  f.seek(pos)
  return end

def copyData(src, dst, count = -1):
  """
  Copy @p count bytes from @p src to @p dst.

  @param[in,out] src Open file to read bytes from.
  @param[in,out] dst Open file to write bytes to.
  @param[in] count Number of bytes to copy.  If -1, bytes are copied until EOF on @p src.
  @return The number of bytes copied.
  """
  done = 0
  if count is None: count = -1

  # Slow read/write loop
  # TODO: use os.sendfile on Linux
  while count < 0 or done < count:
    want = min(IO_BLOCK_SIZE, count-done) if count >= 0 else IO_BLOCK_SIZE
    block = src.read(want)
    if len(block) == 0:
      if count >= 0:
        raise IOError(f"copyData: tried to copy {count} bytes but actually did {done}")
      return done
    dst.write(block)
    done += len(block)
  return done


class BoxSpec:
  __slots__ = ['boxtype','typeIsWildcard','typeCaseInsensitive','typeIncludesBrobs',
               'instanceRange','indexRange']
  def __init__(self, boxspec):
    self.boxtype = None
    self.typeIsWildcard = self.typeCaseInsensitive = False
    self.typeIncludesBrobs = True
    self.instanceRange = self.indexRange = None

    if len(boxspec) == 0:
      return

    propertyValue = boxspec.split('=', maxsplit=1)
    if len(propertyValue) == 2:
      prop,val = propertyValue

      if prop == 'i':
        limits = val.split('..', maxsplit=1)
        try:
          self.indexRange = [None if len(limits[0]) == 0 else int(limits[0]), None]
          if len(limits) < 2:
            self.indexRange[1] = self.indexRange[0]
          else:
            self.indexRange[1] = None if len(limits[1]) == 0 else int(limits[1])
        except ValueError:
          raise InvalidBoxSpec('Invalid syntax for "i" specifier')
        return

      propLower = prop.lower()
      if propLower in ('type','itype','type~','itype~'):
        if propLower[-1] == '~':
          self.typeIsWildcard = True
          prop = prop[:-1]
        if propLower[0] == 'i':
          self.typeCaseInsensitive = True
          prop = prop[1:]
        if prop == 'TYPE':
          self.typeIncludesBrobs = False
        self.boxtype = (val.lower() if self.typeCaseInsensitive else val).encode('ASCII')
        return

      # TODO: come up with some syntax for "nth instance of this type"

    quotedBoxSpec = shlex.quote(boxspec)
    hint = f'.  Did you mean type={quotedBoxSpec}?' if isValidBoxType(boxspec) else ''
    raise InvalidBoxSpec(f'Unknown box specifier, {quotedBoxSpec}{hint}')

  def matches(self, i, box, innerType, instance):
    if self.indexRange is not None and \
        ((self.indexRange[0] is not None and i < self.indexRange[0]) or \
         (self.indexRange[1] is not None and i > self.indexRange[1])):
      return False
    if self.instanceRange is not None and \
        (instance < self.instanceRange[0] or instance > self.instanceRange[1]):
      return False
    if self.boxtype is not None:
      effectiveType = box.boxtype if (not self.typeIncludesBrobs or innerType is None) \
                                  else innerType
      if self.typeCaseInsensitive:
        effectiveType = effectiveType.lower()
      if self.typeIsWildcard:
        if not fnmatch.fnmatchcase(effectiveType, self.boxtype):
          return False
      elif effectiveType != self.boxtype:
        return False
    return True

class BoxCutterException(Exception):
  """Abstract base class for all custom exceptions."""
  pass

class InvalidBmffError(BoxCutterException):
  """File doesn't seem to be in ISO BMFF-like format."""
  pass

class RawJxlError(InvalidBmffError):
  """File is a raw JXL codestream."""
  pass

class InvalidJxlContainerError(BoxCutterException):
  """File is not a valid JXL container (but may be valid as some other BMFF format)."""
  pass

class UsageError(BoxCutterException):
  """API usage error."""
  pass

class InvalidBoxSpec(BoxCutterException):
  """Invalid specifier passed to filter function."""
  pass

class BoxDetails:
  """
  Information about a box.

  offset - Distance in bytes from the start of the file to the start of this box.
  length - Size of this box in bytes, including header.  May be 0 if the box extends to the
           end of the file.
  boxtype - 4-byte box type.
  """
  __slots__ = ['offset', 'length', 'boxtype', 'hasExtendedSize']
  def __init__(self, offset, length, boxtype, hasExtendedSize=False):
    self.offset = offset
    self.length = length
    self.boxtype = boxtype
    self.hasExtendedSize = hasExtendedSize

  def clone(self):
    return BoxDetails(self.offset, self.length, self.boxtype, self.hasExtendedSize)

  def __str__(self):
    return f'{self.length}-byte {shlex.quote(self.boxtype.decode("ASCII"))} box' \
           f'{" with extended size" if self.hasExtendedSize else ""}' \
           f' at offset 0x{self.offset:x}'


class BoxReader:
  __slots__ = ['_filename', '_file', '_index', '_currentBoxDetail', '_currentBoxHeader',
               '_nextBoxOffset', '_eof', '_off', '_doneIter', '_ourFile',
               '_clientBoxDataOffset','_clientIsReadingFull','_clientIsReadingPayload']

  def __init__(self, source):
    self._ourFile = False
    self.open(source)

  def open(self, source):
    """
    Open an ISO BMFF type file for reading.

    This automatically closes any file currently being read by this object.

    @param source May be a file name (str or bytes) or an open binary file-like object.
                  If a file name is given, the file is opened and closed internally.
                  If a file-like object is given, reading starts at the current
                  seek position.
    """
    self.close()
    self._filename = str(source)

    if isinstance(source, str) or isinstance(source, bytes):
      self._ourFile = True
      self._file = open(source, 'rb')
    else:
      self._ourFile = False
      self._file = source
    self._index = -1
    self._currentBoxDetail = None
    self._currentBoxHeader = None
    self._nextBoxOffset = 0
    # How may bytes of the current box's data (full or payload) we've given to the client
    self._clientBoxDataOffset = -1
    self._clientIsReadingFull = False
    self._clientIsReadingPayload = False
    self._eof = False
    self._off = 0
    self._doneIter = False

  def close(self):
    """
    Clean up resources used by this object, closing the file handle if applicable.

    When using this object as a context manager, this is called automatically on exit
    from the 'with' block.  Calling `open` on this object will also implicitly close
    the current file, if any.
    """
    if self._ourFile:
      self._file.close()
    self._ourFile = False
    self._eof = True

  def __enter__(self):
    return self

  def __exit__(self, exc_type, exc_value, traceback):
    self.close()

  def __iter__(self):
    if self._doneIter:
      raise UsageError("You can only iterate over a BoxReader once.")
    self._doneIter = True
    return self

  def __next__(self):
    nextBox = self.nextBox()
    if nextBox is None: raise StopIteration
    return nextBox

  def __str__(self):
    return f'BoxReader for {shlex.quote(self._filename)}, at index {self._index}'

  def nextBox(self):
    if self._eof:
      self._index = -1
      return None

    # Seek to the next box
    seekBy = self._nextBoxOffset - self._off
    self._seekBy(seekBy)
    self._index += 1
    self._clientBoxDataOffset = 0
    self._clientIsReadingFull = self._clientIsReadingPayload = False

    # Read the box header
    try:
      self._currentBoxHeader = self._read(8, allowZero=True)
    except InvalidBmffError as ex:
      sys.stderr.write(f'Truncated header for box index {self._index}.\n')
      raise
    # First box: check for raw JXL codestream
    if self._index == 0 and self._currentBoxHeader.startswith(b'\xff\n') and \
       not isValid4cc(self._currentBoxHeader[4:]):
      raise RawJxlError()
    if len(self._currentBoxHeader) == 0:
      # No more boxes
      self._eof = True
      self._index = -1
      self._clientBoxDataOffset = -1
      return None

    newBox = BoxDetails(self._nextBoxOffset, None, None)

    (newBox.length,) = struct.unpack('>I', self._currentBoxHeader[:4])
    if newBox.length == 1:
      extSizeBytes = self._read(8)
      self._currentBoxHeader += extSizeBytes
      if len(extSizeBytes) != 8: raise InvalidBmffError("Truncated extended box header.")
      (newBox.length,) = struct.unpack('>Q', extSizeBytes)
      newBox.hasExtendedSize = True
    if newBox.length == 0:
      self._eof = True
    newBox.boxtype = self._currentBoxHeader[4:8]
    if not isValid4cc(newBox.boxtype):
      raise InvalidBmffError(f'Invalid box type: {newBox.boxtype}')
    if newBox.length > 0 and newBox.length < len(self._currentBoxHeader):
      raise InvalidBmffError(f'`{newBox.boxtype}` box with declared length of ' \
                            f'{newBox.length} has {len(self._currentBoxHeader)} bytes ' \
                             'in its header.')

    self._currentBoxDetail = newBox
    self._nextBoxOffset = (self._nextBoxOffset + newBox.length) if newBox.length > 0 \
                          else None
    return newBox.clone()

  def finalBoxSize(self):
    """
    Can only be called having exhausted the list of boxes.  If the last box size is 0,
    this tries to find the end of the file and reports its real size.

    This may read the full box data, preventing any more calls to this object's read* methods.
    """
    if not self._eof: raise UsageError("Can't call finalBoxSize before we've reached " \
                                       "the final box.")
    if self._currentBoxDetail.length > 0: return self._currentBoxDetail.length

    while True:
      # seek/_seekBy will go past EOF, so never finds the end.
      block = self._read(IO_BLOCK_SIZE, allowShort=True)
      if len(block) < IO_BLOCK_SIZE:
        self._currentBoxDetail.length = self._off - self._currentBoxDetail.offset
        return self._currentBoxDetail.length

  def copyCurrentBoxPayload(self, to, n=-1):
    """
    See @ref readCurrentBoxPayload.  This function behaves exactly the same, but the
    data is written directly to the open file-like object, `to`, and the number of bytes
    written is returned.
    """
    if self._clientIsReadingFull:
      raise UsageError("Can't read the payload after starting to read the full box.")
    if self._clientBoxDataOffset < 0: raise UsageError('No box available.')
    self._clientIsReadingPayload = True

    if self._currentBoxDetail.length == 0:
      maxRead = n if n >= 0 else -1
      allowShort = True
    else:
      maxRead = self._currentBoxDetail.length - len(self._currentBoxHeader) \
                  - self._clientBoxDataOffset
      if n >= 0:
        maxRead = min(maxRead, n)
      allowShort = n <= maxRead # including when n < 0
    copiedBytes = copyData(self._file, to, maxRead)
    self._off += copiedBytes
    self._clientBoxDataOffset += copiedBytes
    if not allowShort and copiedBytes != maxRead:
      raise InvalidBmffError(f'Tried to copy {maxRead} bytes of box content, but only ' \
                            f'copied {copiedBytes}.')
    return copiedBytes

  def readCurrentBoxPayload(self, n = -1):
    """
    Read up to `n` bytes of payload from the current box.
    This can only be called after fetching a box via `nextBox` or `next()`.
    You can call this multiple times until the payload is exhausted.

    Calling `nextBox` or iterating the BoxReader object will skip any remaining unread
    payload bytes and prepare to read data from the next box.

    `readCurrentBoxPayload` / `copyCurrentBoxPayload` cannot be used on the same box
    as `readCurrentBox` / `copyCurrentBox`.  Whichever flavour you use first is the
    only one that is allowed until the next box is fetched.

    Passing -1 will return the entire remaining payload.  Otherwise, you will get exactly
    `n` bytes returned unless the end of the payload is reached.
    """
    with io.BytesIO() as dst:
      self.copyCurrentBoxPayload(dst, n)
      return dst.getvalue()

  def seekCurrentBoxPayload(self, n):
    """
    Discard up to `n` bytes of payload data, returning the number actually discarded.
    TODO: faster implementation.
    """
    remain = n
    while remain > 0:
      want = min(remain, IO_BLOCK_SIZE)
      skipped = self.readCurrentBoxPayload(want)
      remain -= len(skipped)
      if len(skipped) < want:
        return n - remain
    return n

  def copyCurrentBox(self, to, n = -1):
    """
    See @ref readCurrentBox.  This function behaves exactly the same, but the data is
    written directly to the open file-like object, `to`, and the number of bytes written
    is returned.
    """
    if self._clientIsReadingPayload:
      raise UsageError("Can't read the full box after starting to read the payload.")
    if self._clientBoxDataOffset < 0: raise UsageError('No box available.')
    self._clientIsReadingFull = True

    totalCopied = 0
    availableHeaderBytes = len(self._currentBoxHeader) - self._clientBoxDataOffset
    if availableHeaderBytes > 0:
      want = min(availableHeaderBytes, n) if n >= 0 else availableHeaderBytes
      end = self._clientBoxDataOffset + want
      if to.write(self._currentBoxHeader[self._clientBoxDataOffset:end]) != want:
        raise IOError(f'copyCurrentBox: failed to copy {want} bytes of box header data.\n')
      self._clientBoxDataOffset += want
      totalCopied = want
      if totalCopied == n:
        return totalCopied

    if self._currentBoxDetail.length > 0:
      availablePayloadBytes = self._currentBoxDetail.length - self._clientBoxDataOffset
      want = min(availablePayloadBytes, n-totalCopied) if n >= 0 \
               else availablePayloadBytes
    else:
      want = -1

    bytesCopied = copyData(self._file, to, want)
    self._off += bytesCopied
    self._clientBoxDataOffset += bytesCopied
    totalCopied += bytesCopied
    if bytesCopied != want and want != -1:
      raise InvalidBmffError(f'Tried to copy {want} bytes of box content, but only ' \
                            f'copied {bytesCopied}.')
    return totalCopied

  def readCurrentBox(self, n = -1):
    """
    Read up to `n` bytes of the current box, including its header.
    This can only be called after fetching a box via `nextBox` or `next()`.
    You can call this multiple times until the end of the current box is reached.

    Calling `nextBox` or iterating the BoxReader object will skip any remaining unread
    bytes of the current box and prepare to read data from the next box.

    `readCurrentBoxPayload` / `copyCurrentBoxPayload` cannot be used on the same box
    as `readCurrentBox` / `copyCurrentBox`.  Whichever flavour you use first is the
    only one that is allowed until the next box is fetched.

    Passing -1 will return all remaining bytes of the current box.  Otherwise, you will
    get exactly `n` bytes returned unless the end of the box is reached.
    """
    with io.BytesIO() as dst:
      self.copyCurrentBox(dst, n)
      return dst.getvalue()

  def seekCurrentBox(self, n):
    """
    Discard up to `n` bytes of box data, returning the number actually discarded.
    TODO: faster implementation.
    """
    remain = n
    while remain > 0:
      want = min(remain, IO_BLOCK_SIZE)
      skipped = self.readCurrentBox(want)
      remain -= len(skipped)
      if len(skipped) < want:
        return n - remain
    return n

  def _read(self, count, allowZero=False, allowShort=False):
    data = self._file.read(count)
    dlen = len(data)
    self._off += dlen
    if count != -1 and \
       dlen != count and \
       not (allowZero and dlen == 0) and \
       not (allowShort and dlen < count):
      raise InvalidBmffError(f'Tried to read {count} bytes but got {len(data)}.')
    return data

  def _seekBy(self, count, exact=True):
    """
    Seek the file position by @p count relative to the current position.

    If the file isn't seekable (and count is positive), @p count bytes are read and
    discarded.  self._off is updated to reflect the new stream position.

    @return the number of bytes skipped.
    """
    if self._file.seekable():
      self._file.seek(count, io.SEEK_CUR)
      self._off += count
      return count
    if count < 0:
      raise UsageError("Can't seek backwards in a non-seekable file.")
    done = 0
    while done < count:
      block = self._file.read(min(IO_BLOCK_SIZE, count-done))
      self._off += len(block)
      if len(block) == 0:
        if exact:
          raise InvalidBmffError(f"_seekBy: tried to seek {count} bytes but actually ' \
                                f'did {done}")
        return done
      done += len(block)
    return done



class CatReader:
  """
  Forward-only, read-only, binary, file-like object that presents a sequence of input
  streams as if they were a single file consisting of the (remaining) content of the
  inputs concatenated together.

  Instances are single-use and cannot be reopened.

  `seek` and `tell` behave correctly based on the virtual concatented file, with the
  following restrictions:
  - You can't seek to an earlier position in the file.
  - You can't seek relative to io.SEEK_END.
  If the underlying streams aren't seekable, seeking is implemented with a read loop,
  which is slow, but otherwise transparent to the client.

  Inputs can be a mixture of readable binary files and `bytes` objects.
  """

  def __init__(self, closeFiles, *files):
    self._off = 0
    self._files = list(files)
    self._sizes = [-1] * len(files)
    self._mustClose = [closeFiles] * len(files)
    # Create BytesIO wrappers for bytes inputs - always close them later
    for i in range(len(files)):
      if isinstance(self._files[i], bytes):
        self._files[i] = io.BytesIO(files[i])
        self._files[i].seek(0)
        self._mustClose[i] = True
    self._eof = len(files) == 0
    self._currentFileIx = 0
    self.closed = False

  def __enter__(self):
    return self

  def __exit__(self, exc_type, exc_value, traceback):
    if self.closed: return
    self.close()

  def close(self):
    for i,f in enumerate(self._files[self._currentFileIx:]):
      if self._mustClose[i]:
        f.close()
    self._currentFileIx = len(self._files)
    self._eof = True
    self.closed = True

  def read(self, n=-1):
    if n is None or n == -1: return self.readall()
    if self._eof: return b''
    stillWant = n
    returndata = b''
    while True:
      data = self._files[self._currentFileIx].read(stillWant)
      gotBytes = len(data)
      self._off += gotBytes
      stillWant -= gotBytes
      returndata += data
      if stillWant == 0:
        return returndata
      if self._currentFileIx == len(self._files) - 1:
        self._eof = True
        return returndata
      if self._mustClose[self._currentFileIx]:
        self._files[self._currentFileIx].close()
        self._mustClose[self._currentFileIx] = False
      self._currentFileIx += 1

  def readall(self):
    if self._eof: return b''
    returndata = b''
    while self._currentFileIx < len(self._files):
      data = self._files[self._currentFileIx].read()
      self._off += len(data)
      returndata += data
      if self._mustClose[self._currentFileIx]:
        self._files[self._currentFileIx].close()
        self._mustClose[self._currentFileIx] = False
      self._currentFileIx += 1
    eof = True
    return returndata

  def tell(self):
    return self._off

  def seek(self, n, whence = io.SEEK_SET):

    if whence == io.SEEK_SET:
      whence = io.SEEK_CUR
      n -= self._off
      if n < 0: raise IOError('Seeking backwards not implemented.')
    elif whence != io.SEEK_CUR:
      raise IOError('Seek method not implemented.')

    if self._eof:
      self._off += n
      return self._off

    stillWant = n
    while True:
      currentFile = self._files[self._currentFileIx]
      if currentFile.seekable():
        startedAt = currentFile.tell()
        # Seek will allow us to go past the end of the file, so we need to
        # know the size in advance to avoid overshooting.  Doesn't matter for the
        # last file.
        isLastFile = self._currentFileIx == len(self._files) - 1
        if not isLastFile and self._sizes[self._currentFileIx] == -1:
          currentFile.seek(0, io.SEEK_END)
          self._sizes[self._currentFileIx] = currentFile.tell()
          currentFile.seek(startedAt, io.SEEK_SET)
        if not isLastFile and startedAt + stillWant >= self._sizes[self._currentFileIx]:
          skipped = self._sizes[self._currentFileIx] - startedAt
        else:
          skipped = currentFile.seek(stillWant, io.SEEK_CUR) - startedAt
        self._off += skipped
        stillWant -= skipped
        if stillWant <= 0: # We may go past the end of the last file
          return self._off
      else:
        # Read and discard until we've skipped enough bytes or we get to local EOF
        while True:
          want = min(IO_BLOCK_SIZE, stillWant)
          ignored = currentFile.read(want)
          skipped = len(ignored)
          self._off += skipped
          stillWant -= skipped
          if stillWant == 0:
            return self._off
          if skipped < want:
            break

      # local eof, and still want to skip more
      if self._currentFileIx == len(self._files) - 1:
        self._eof = True
        return self._off
      self._currentFileIx += 1

  def flush(self): pass
  def isatty(self): return False
  def readable(self): return True
  def seekable(self): return False
  def writable(self): return False
  def fileno(self): raise OSError('CatReader does not have a fileno.')



if __name__ == '__main__':
  sys.exit(main(sys.argv))



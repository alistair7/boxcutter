#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) Alistair Barrow. All rights reserved.
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file.

import io
import struct
import sys
import unittest
import boxcutter

from os.path import dirname, realpath
TESTFILES = f'{dirname(realpath(__file__))}/testfiles'

class TestCatReader(unittest.TestCase):

  def testNoFiles(self):
    with boxcutter.CatReader(False) as reader:
      self.assertEqual(reader.read(), b'')
      self.assertEqual(reader.tell(), 0)

  def testReadSingleEmptyFile(self):
    with io.BytesIO() as empty:

      with boxcutter.CatReader(False, empty) as reader:
        self.assertEqual(reader.read(), b'')
      empty.seek(0) # Should not throw, as file should remain open

      with boxcutter.CatReader(True, empty) as reader:
        self.assertEqual(reader.readall(), b'')
      self.assertRaises(ValueError, empty.seek, 0) # Should throw, as file should be closed

    # Test reading bytes object
    with boxcutter.CatReader(False, b'') as reader:
      self.assertEqual(reader.read(), b'')

  def testReadSingleNonEmptyFile(self):
    with io.BytesIO(b'data') as f:
      with boxcutter.CatReader(False, f) as reader:
        self.assertEqual(reader.read(), b'data')
      f.seek(0) # Should not throw, as file should remain open
      with boxcutter.CatReader(True, f) as reader:
        self.assertEqual(reader.read(), b'data')
      self.assertRaises(ValueError, f.seek, 0) # Should throw, as file should be closed

    # Test reading bytes object
    with boxcutter.CatReader(False, b'data') as reader:
      self.assertEqual(reader.read(), b'data')

  def testReadMultiFiles(self):
    with io.BytesIO(b'one') as f1, \
         io.BytesIO(b'two') as f2:
      f1.seek(0)
      f2.seek(0)
      with boxcutter.CatReader(False, f1, f2, b'three') as reader:
        self.assertEqual(reader.read(), b'onetwothree')
        self.assertEqual(reader.tell(), 11)
      f1.seek(0)
      f2.seek(0)

      with boxcutter.CatReader(True, f1, f2, b'three') as reader:
        self.assertEqual(reader.read(), b'onetwothree')
      self.assertRaises(ValueError, f1.seek, 0)
      self.assertRaises(ValueError, f2.seek, 0)

  def testSeek(self):
    with io.BytesIO(b'one') as f1, \
         io.BytesIO(b'two') as f2:
      f1.seek(0)
      f2.seek(0)
      with boxcutter.CatReader(False, f1, f2, b'three') as reader:
        self.assertEqual(reader.tell(), 0)
        self.assertEqual(reader.seek(1), 1)
        self.assertEqual(reader.seek(1, io.SEEK_CUR), 2)
        self.assertEqual(reader.read(5), b'etwot')
        self.assertEqual(reader.tell(), 7)
        self.assertEqual(reader.read(100), b'hree')
        self.assertEqual(reader.tell(), 11)


class TestCount(unittest.TestCase):

  def testCountEmpty(self):
    for mode in (boxcutter.MODE_COUNT, boxcutter.MODE_HAS):
      for boxspecList in ([], ['type=JXL ']):
        self.assertEqual(boxcutter.doScanBoxes(io.BytesIO(), None, mode, boxspecList), 0,
                         msg=f'mode={mode}; boxspecList={boxspecList}')

  def testCountRawJxl(self):
    with open(f'{TESTFILES}/pixel-raw.jxl', 'rb') as jxl:
      for mode in (boxcutter.MODE_COUNT, boxcutter.MODE_HAS):
        for boxspecList in ([], ['type=JXL ']):
          self.assertEqual(boxcutter.doScanBoxes(jxl, None, mode, boxspecList),
                           boxcutter.RAW_JXL,
                           msg=f'mode={mode}; boxspecList={boxspecList}')
          jxl.seek(0)

  def testCountSimple(self):
    with open(f'{TESTFILES}/various-boxes.4cc', 'rb') as jxl:
      self.assertEqual(boxcutter.doScanBoxes(jxl, None, boxcutter.MODE_COUNT, None), 4)
      jxl.seek(0)
      self.assertEqual(boxcutter.doScanBoxes(jxl, None, boxcutter.MODE_HAS, None), 1)
      jxl.seek(0)
      self.assertEqual(boxcutter.doScanBoxes(jxl, None, boxcutter.MODE_COUNT,
                                             ['type=BBBB']), 1)
      jxl.seek(0)
      self.assertEqual(boxcutter.doScanBoxes(jxl, None, boxcutter.MODE_HAS,
                                             ['type=BBBB']), 1)

    with open(f'{TESTFILES}/pixel-jxlp-stupid.jxl', 'rb') as jxl:
      for mode,expect in ( (boxcutter.MODE_COUNT, 7), (boxcutter.MODE_HAS, 1)):
        self.assertEqual(boxcutter.doScanBoxes(jxl, None, mode, ['i=0','type=jxlp']),
                         expect, msg=f'mode={mode}')
        jxl.seek(0)

  def testCountInvalid(self):
    with io.BytesIO(b'\0') as jxl:
      for mode in (boxcutter.MODE_COUNT, boxcutter.MODE_HAS):
        self.assertEqual(boxcutter.doScanBoxes(jxl, None, mode, None),
                         boxcutter.FAILED_PARSE, msg=f'mode={mode}')
        jxl.seek(0)
    with io.BytesIO(b'\0\0\0\x09ABCD\0\0\0\x09EFGH\t') as jxl:
      for mode,expect in ((boxcutter.MODE_COUNT, boxcutter.FAILED_PARSE),
                          (boxcutter.MODE_HAS, boxcutter.FAILED_PARSE)):
        self.assertEqual(boxcutter.doScanBoxes(jxl, None, mode, None), expect,
                         msg=f'mode={mode}')
        jxl.seek(0)
    with io.BytesIO(b'\0\0\0\x09ABCD\0\0\0\x09EFGHx') as jxl:
      # Malformed - MODE_HAS stops after reading the first box, so doesn't detect a problem.
      for mode,expect in ((boxcutter.MODE_COUNT,boxcutter.FAILED_PARSE),
                          (boxcutter.MODE_HAS,1)):
        self.assertEqual(boxcutter.doScanBoxes(jxl, None, mode, None), expect)
        jxl.seek(0)

class TestExtractBox(unittest.TestCase):

  def testExtractNothing(self):
    with open(f'{TESTFILES}/various-boxes.4cc', 'rb') as src, \
         io.BytesIO() as dst:
      self.assertNotEqual(boxcutter.doExtractBox(src, dst, []), 0)
      src.seek(0)
      self.assertNotEqual(boxcutter.doExtractBox(src, dst, ['i=100']), 0)

  def testExtractBox(self):
    with open(f'{TESTFILES}/various-boxes.4cc', 'rb') as src, \
         io.BytesIO() as dst:
      self.assertEqual(boxcutter.doExtractBox(src, dst, ['i=0']), 0)
      self.assertEqual(dst.getvalue(), b'')

      src.seek(0)
      dst.seek(0)
      dst.truncate()
      self.assertEqual(boxcutter.doExtractBox(src, dst, ['i=1..']), 0)
      self.assertEqual(dst.getvalue(), b'bbb')

      src.seek(0)
      dst.seek(0)
      dst.truncate()
      self.assertEqual(boxcutter.doExtractBox(src, dst, ['i=99', 'itype~=Cc?c']), 0)
      self.assertEqual(dst.getvalue(), b'ccccc')

    # Extracting a jxlc payload is the same as extracting the JXL codestream
    with open(f'{TESTFILES}/pixel-jxlc.jxl', 'rb') as src, \
         io.BytesIO() as dst1, io.BytesIO() as dst2:
      self.assertEqual(boxcutter.doExtractBox(src, dst1, ['type=jxlc']), 0)
      src.seek(0)
      self.assertEqual(boxcutter.extractJxlCodestream(src, dst2, False), 0)
      self.assertEqual(dst1.getvalue(), dst2.getvalue())

  def testDecompressBox(self):
    if not boxcutter.HAVE_BROTLI:
      return

    compOpts = boxcutter.CompressionOpts(
                 decompressWhen=boxcutter.CompressionOpts.DECOMPRESS_ALWAYS,
                 decompressMax=-1)

    with open(f'{TESTFILES}/pixel.jpg.jxl', 'rb') as src, \
         io.BytesIO() as dst:
      self.assertEqual(boxcutter.doExtractBox(src, dst, ['TYPE=brob'], compOpts), 0)
      decompressedExif = dst.getvalue()
      self.assertEqual(decompressedExif[:8], b'\0\0\0\0II*\0')
      self.assertEqual(len(decompressedExif), 264)

      dst.seek(0)
      dst.truncate()
      src.seek(0)
      compOpts.decompressMax = 264
      self.assertEqual(boxcutter.doExtractBox(src, dst, ['TYPE=brob'], compOpts), 0)
      self.assertEqual(len(dst.getvalue()), 264)

      dst.seek(0)
      dst.truncate()
      src.seek(0)
      compOpts.decompressMax = 263
      self.assertRaises(boxcutter.TooMuchDataError, boxcutter.doExtractBox, src, dst,
                        ['TYPE=brob'], compOpts)
      self.assertTrue(len(dst.getvalue()) <= 263)

      dst.seek(0)
      dst.truncate()
      src.seek(0)
      compOpts.decompressMax = -1
      try:
        boxcutter.HAVE_BROTLI = False
        self.assertNotEqual(boxcutter.doExtractBox(src, dst, ['TYPE=brob'], compOpts), 0)
      finally:
        boxcutter.HAVE_BROTLI = True

class TestExtractCodestream(unittest.TestCase):

  def setUp(self):
    with open(f'{TESTFILES}/pixel-raw.jxl', 'rb') as raw:
      self.jxlcodestream = raw.read()

  def testAlreadyACodestream(self):
    with io.BytesIO(self.jxlcodestream) as src, \
         io.BytesIO() as dst:
      self.assertNotEqual(boxcutter.extractJxlCodestream(src, dst, False), 0)
      src.seek(0)
      self.assertEqual(boxcutter.extractJxlCodestream(src, dst, True), 0)
      self.assertEqual(dst.getvalue(), self.jxlcodestream)

  def testJxlc(self):
    with open(f'{TESTFILES}/pixel-jxlc.jxl', 'rb') as jxl, \
         io.BytesIO() as result:
      self.assertEqual(boxcutter.extractJxlCodestream(jxl, result, False), 0)
      self.assertEqual(result.getvalue(), self.jxlcodestream)

  def testJxlp(self):
    for suffix in ('8','single','stupid'):
      fname = f'{TESTFILES}/pixel-jxlp-{suffix}.jxl'
      with open(fname, 'rb') as jxl, \
           io.BytesIO() as result:
        self.assertEqual(boxcutter.extractJxlCodestream(jxl, result, False), 0)
        self.assertEqual(result.getvalue(), self.jxlcodestream,
                         msg=f'Failed to get correct codestream from {fname}')

  def testJxlpWrongSequence(self):
    with open(f'{TESTFILES}/pixel-jxlp-badsequence.jxl', 'rb') as jxl, \
         io.BytesIO() as result:
      self.assertNotEqual(boxcutter.extractJxlCodestream(jxl, result, False), 0)


class TestWrapCodestream(unittest.TestCase):

  def setUp(self):
    with open(f'{TESTFILES}/pixel-raw.jxl', 'rb') as raw:
      self.jxlcodestream = raw.read()

  def testAlreadyAContainer(self):
    with open(f'{TESTFILES}/pixel-jxlc.jxl', 'rb') as src, \
         io.BytesIO() as dst:
      original = src.read()

      src.seek(0)
      self.assertNotEqual(boxcutter.addContainer(src, dst, ifNeeded=False), 0)
      src.seek(0)
      self.assertEqual(boxcutter.addContainer(src, dst, ifNeeded=True), 0)
      self.assertEqual(dst.getvalue(), original)
      src.seek(0)
      dst.seek(0)
      dst.truncate()
      self.assertEqual(boxcutter.addContainer(src, dst, ifNeeded=True,
                                              jxll=10, splits=[5]), 0)
      self.assertEqual(dst.getvalue(), original)

  def testJxlc(self):
    with open(f'{TESTFILES}/pixel-jxlc.jxl', 'rb') as f:
      expect = f.read()

    with io.BytesIO(self.jxlcodestream) as src, \
         io.BytesIO() as dst:
      src.seek(0)
      self.assertEqual(boxcutter.addContainer(src, dst, False), 0)
      self.assertEqual(dst.getvalue(), expect)

    expect = boxcutter.JXL_CONTAINER_SIG + \
             b'\0\0\0\x14ftypjxl \0\0\0\0jxl ' + \
             b'\0\0\0\x09jxll\x0a' + \
             struct.pack('>I', 8 + len(self.jxlcodestream)) + b'jxlc' + \
             self.jxlcodestream

    with io.BytesIO(self.jxlcodestream) as src, \
         io.BytesIO() as dst:
      src.seek(0)
      self.assertEqual(boxcutter.addContainer(src, dst, False, jxll=10), 0)
      self.assertEqual(dst.getvalue(), expect)

  def testJxlpSensible(self):
    with open(f'{TESTFILES}/pixel-jxlp-8.jxl', 'rb') as f:
      expect = f.read()
    with io.BytesIO(self.jxlcodestream) as src, \
         io.BytesIO() as dst:
      src.seek(0)
      self.assertEqual(boxcutter.addContainer(src, dst, False, splits=[8]), 0)
      self.assertEqual(dst.getvalue(), expect)

  def testJxlpStupid(self):
    with open(f'{TESTFILES}/pixel-jxlp-single.jxl', 'rb') as f:
      expect = f.read()

    with io.BytesIO(self.jxlcodestream) as src, \
         io.BytesIO() as dst:
      src.seek(0)
      self.assertEqual(boxcutter.addContainer(src, dst, False, splits=[]), 0)
      self.assertEqual(dst.getvalue(), expect)

    with open(f'{TESTFILES}/pixel-jxlp-stupid.jxl', 'rb') as f:
      expect = f.read()

    with io.BytesIO(self.jxlcodestream) as src, \
         io.BytesIO() as dst:
      src.seek(0)
      self.assertEqual(boxcutter.addContainer(src, dst, False,
                                              splits=[0,8,9,11,9]), 0)
      self.assertEqual(dst.getvalue(), expect)


class TestAdd(unittest.TestCase):

  def testAddToEmpty(self):
    with io.BytesIO() as empty, \
         io.BytesIO() as result:
      self.assertEqual(boxcutter.doAddBoxes(empty, result, [], 'utf-8'), 0)
      self.assertEqual(result.getvalue(), b'')

    for position in (-1, 0):
      with io.BytesIO() as empty, \
           io.BytesIO() as result:
          self.assertEqual(boxcutter.doAddBoxes(empty, result,
                                                ['utf8=café','empt=',f'ABOX@{TESTFILES}/a'],
                                                'utf-8', at=position), 0,
                           msg=f'Position {position}')
          self.assertEqual(result.getvalue(), b'\0\0\0\x0dutf8caf\xc3\xa9\0\0\0\x08empt' \
                                              b'\0\0\0\x0aABOXa\n',
                           msg=f'Position {position}')

    # Can't add at position > 0
    with io.BytesIO() as empty, \
         io.BytesIO() as result:
      self.assertNotEqual(boxcutter.doAddBoxes(empty, result, ['utf8=café'], 'utf-8',
                                               at=1), 0)

  def testAppend(self):
    with open(f'{TESTFILES}/various-boxes.4cc', 'rb') as f:
      original = f.read()
    # Replace size 0 with size 34
    originalWithExplicitSize = original[:-31] + b'\x22' + original[-30:]

    # Adding anything (or nothing) to a file with an implicitly-sized final box
    # will try to make the size explicit, even if it doesn't strictly need to.
    with io.BytesIO(original) as src, \
         io.BytesIO() as dst:
      src.seek(0)
      self.assertEqual(boxcutter.doAddBoxes(src, dst, [], 'utf-8'), 0)
      self.assertEqual(originalWithExplicitSize, dst.getvalue())

    # If input is unseekable/unstat-able, size can be set by seeking back the output
    with boxcutter.CatReader(False, original) as src, \
         io.BytesIO() as dst:
      src.seek(0)
      self.assertEqual(boxcutter.doAddBoxes(src, dst, [], 'utf-8'), 0)
      self.assertEqual(originalWithExplicitSize, dst.getvalue())
    # If output is unseekable/unstat-able, size can be set by checking the size of the input
    with io.BytesIO(original) as src, \
         io.BytesIO() as dst:
      src.seek(0)
      dst.seekable = lambda : False
      self.assertEqual(boxcutter.doAddBoxes(src, dst, [], 'utf-8'), 0)
      self.assertEqual(originalWithExplicitSize, dst.getvalue())
    # If neither input nor output are seekable/stat-able, setting the size isn't possible.
    # But if we're not appending anything, this is OK.
    with boxcutter.CatReader(False, original) as src, \
         io.BytesIO() as dst:
      src.seek(0)
      dst.seekable = lambda : False
      self.assertEqual(boxcutter.doAddBoxes(src, dst, [], 'utf-8'), 0)
      self.assertEqual(original, dst.getvalue())
    with boxcutter.CatReader(False, original) as src, \
         io.BytesIO() as dst:
      src.seek(0)
      dst.seekable = lambda : False
      self.assertNotEqual(boxcutter.doAddBoxes(src, dst, ['fail='], 'utf-8'), 0)

    for position in (-1, 4):
      with io.BytesIO(original) as src, \
           io.BytesIO() as dst:
        src.seek(0)
        self.assertEqual(boxcutter.doAddBoxes(src, dst, ['empt=',f'ABOX@{TESTFILES}/a'],
                                              'utf-8', at=position), 0,
                         msg=f'Position {position}')
        self.assertEqual(originalWithExplicitSize + b'\0\0\0\x08empt\0\0\0\x0aABOXa\n',
                         dst.getvalue(),
                         msg=f'Position {position}')

    # Force doAddBoxes to use implicit size for the last box
    with io.BytesIO(original) as src, \
         io.BytesIO(b'payload') as payload, \
         io.BytesIO() as dst:
      src.seek(0)
      dst.seekable = lambda : False
      payload.seek(0)
      payload.seekable = lambda : False
      #payload.fileno = OSError

      class FakeStdin:
        buffer = payload
      saveStdin = sys.stdin
      sys.stdin = FakeStdin
      self.assertEqual(boxcutter.doAddBoxes(src, dst, ['empt=',f'STDI@-'], 'utf-8'), 0)
      sys.stdin = saveStdin

      self.assertEqual(originalWithExplicitSize + b'\0\0\0\x08empt\0\0\0\0STDIpayload',
                       dst.getvalue())

  def testInsert(self):
    with open(f'{TESTFILES}/various-boxes.4cc', 'rb') as f:
      original = f.read()
    # Replace size 0 with size 34
    originalWithExplicitSize = original[:-31] + b'\x22' + original[-30:]

    insertBox = b'\0\0\0\x0ainsert'

    # Try inserting before each of the 4 boxes in various-boxes.4cc, plus adding to the end.
    for position,offset in enumerate([0, 8, 19, 40, 74]):
      with io.BytesIO(original) as src, \
           io.BytesIO() as dst:
        src.seek(0)
        self.assertEqual(
          boxcutter.doAddBoxes(src, dst, ['inse=rt'], 'utf-8', at=position), 0,
          msg=f'Position {position}')
        self.assertEqual(dst.getvalue(),
                         originalWithExplicitSize[:offset] + insertBox + originalWithExplicitSize[offset:],
                         msg=f'Position {position}')

  def testAddNonAscii(self):
    with open(f'{TESTFILES}/various-boxes.4cc', 'rb') as src, \
         io.BytesIO() as dst:
      self.assertNotEqual(boxcutter.doAddBoxes(src, dst, ['ab\tc='], 'utf-8',
                                               compOpts=None), 0)

class TestAddWithCompression(unittest.TestCase):

  @unittest.skipIf(not boxcutter.HAVE_BROTLI, 'Brotli not supported')
  def testAddToEmpty(self):
    for position in (-1, 0):
      with io.BytesIO() as empty, \
           io.BytesIO() as result:
          self.assertEqual(boxcutter.doAddBoxes(empty, result,
                                                ['utf8=café','empt=',f'ABOX@{TESTFILES}/a'],
                                                'utf-8',
                                                compOpts=boxcutter.CompressionOpts(compressWhen=boxcutter.CompressionOpts.COMPRESS_ALWAYS),
                                                at=position), 0,
                           msg=f'Position {position}')
          result.seek(0)
          (boxLen,) = struct.unpack('>I', result.read(4))
          self.assertEqual(result.read(8), b'brobutf8')
          result.seek(boxLen - 4 - 8, io.SEEK_CUR)
          (boxLen,) = struct.unpack('>I', result.read(4))
          self.assertEqual(result.read(8), b'brobempt')
          result.seek(boxLen - 4 - 8, io.SEEK_CUR)
          (boxLen,) = struct.unpack('>I', result.read(4))
          self.assertEqual(result.read(8), b'brobABOX')
          # Since BytesIO is seekable, we SHOULD have set the last size field
          self.assertNotEqual(boxLen, 0)

  @unittest.skipIf(not boxcutter.HAVE_BROTLI, 'Brotli not supported')
  def testNonSeekable(self):
    with open(f'{TESTFILES}/various-boxes.4cc', 'rb') as src:

      # When setting boxes using string literals, we always buffer the whole thing, so
      # we can add any number of boxes anywhere without seeking the output.
      for position in (-1, 0):
        src.seek(0)
        with io.BytesIO() as dst:
          dst.seekable = lambda : False
          self.assertEqual(boxcutter.doAddBoxes(src, dst, ['utf8=café','empt='], 'utf-8',
                                                compOpts=boxcutter.CompressionOpts(compressWhen=boxcutter.CompressionOpts.COMPRESS_ALWAYS)),
                           0, msg=f'Position {position}')

      # When reading box content from files and compressing, we don't know the size
      # before writing the box, so we can only append, and only once.
      for position in (-1, 0):
        src.seek(0)
        with io.BytesIO() as dst:
          dst.seekable = lambda : False
          self.assertEqual(boxcutter.doAddBoxes(src, dst, ['utf8=café',f'ABOX@{TESTFILES}/a'], 'utf-8',
                                                compOpts=boxcutter.CompressionOpts(compressWhen=boxcutter.CompressionOpts.COMPRESS_ALWAYS)),
                           0, msg=f'Position {position}')
      for position in (-1, 0):
        src.seek(0)
        with io.BytesIO() as dst:
          dst.seekable = lambda : False
          with self.assertRaises(boxcutter.UnseekableOutputError, msg=f'Position {position}'):
            boxcutter.doAddBoxes(src, dst, [f'ABOX@{TESTFILES}/a','utf8=café'], 'utf-8',
                                 compOpts=boxcutter.CompressionOpts(compressWhen=boxcutter.CompressionOpts.COMPRESS_ALWAYS))

class TestFilter(unittest.TestCase):

  def testPassthrough(self):
    # Drop nothing
    with open(f'{TESTFILES}/various-boxes.4cc', 'rb') as src, \
         io.BytesIO() as dst:
      original = src.read()
      src.seek(0)
      self.assertEqual(boxcutter.doFilter(src, dst, False, []), 0)
      self.assertEqual(dst.getvalue(), original)

    # Keep nothing
    with open(f'{TESTFILES}/various-boxes.4cc', 'rb') as src, \
         io.BytesIO() as dst:
      self.assertEqual(boxcutter.doFilter(src, dst, True, []), 0)
      self.assertEqual(dst.getvalue(), b'')

  def testRemoveIndexes(self):
    for keep, boxstats in ( (False, ('i=0','i=3','i=1000')),
                            (True, ('i=1..2',)) ):
      with open(f'{TESTFILES}/various-boxes.4cc', 'rb') as src, \
           io.BytesIO() as dst:
        self.assertEqual(boxcutter.doFilter(src, dst, keep, boxstats), 0)
        self.assertEqual(dst.getvalue(), b'\0\0\0\x0bBBBBbbb' \
                                         b'\0\0\0\x01CCCC\0\0\0\0\0\0\0\x15ccccc')

    for keep, boxstat in ((False, 'i=1..'),
                           (True, 'i=..0')):
      with open(f'{TESTFILES}/various-boxes.4cc', 'rb') as src, \
           io.BytesIO() as dst:
        self.assertEqual(boxcutter.doFilter(src, dst, keep, [boxstat]), 0)
        self.assertEqual(dst.getvalue(), b'\0\0\0\x08AAAA')

    with open(f'{TESTFILES}/various-boxes.4cc', 'rb') as src, \
         io.BytesIO() as dst:
      original = src.read()
      src.seek(0)
      self.assertEqual(boxcutter.doFilter(src, dst, True, ['i=..']), 0)
      self.assertEqual(dst.getvalue(), original)

  def testRemoveTypes(self):
    originalWithNoJxlps = boxcutter.JXL_CONTAINER_SIG + b'\0\0\0\x14ftypjxl \0\0\0\0jxl '
    with open(f'{TESTFILES}/pixel-jxlp-8.jxl', 'rb') as src, \
         io.BytesIO() as dst:
      self.assertEqual(boxcutter.doFilter(src, dst, False, ['type=jxlp']), 0)
      self.assertEqual(dst.getvalue(), originalWithNoJxlps)
    with open(f'{TESTFILES}/pixel-jxlp-8.jxl', 'rb') as src, \
         io.BytesIO() as dst:
      original = src.read()
      src.seek(0)
      self.assertEqual(boxcutter.doFilter(src, dst, False, ['type=JXLP']), 0)
      self.assertEqual(dst.getvalue(), original)
    with open(f'{TESTFILES}/pixel-jxlp-8.jxl', 'rb') as src, \
         io.BytesIO() as dst:
      original = src.read()
      src.seek(0)
      self.assertEqual(boxcutter.doFilter(src, dst, False, ['itype=JXLP']), 0)
      self.assertEqual(dst.getvalue(), originalWithNoJxlps)

    with open(f'{TESTFILES}/pixel.jpg.jxl', 'rb') as src, \
         io.BytesIO() as dst1, io.BytesIO() as dst2, io.BytesIO() as dst3:
      original = src.read()
      src.seek(0)
      # This should be equivalent to removing both brob boxes
      self.assertEqual(boxcutter.doFilter(src, dst1, False, ['type=Exif','itype=XML ']), 0)
      src.seek(0)
      self.assertEqual(boxcutter.doFilter(src, dst2, False, ['TYPE=brob']), 0)
      self.assertEqual(dst1.getvalue(), dst2.getvalue())

      # ...but this should have no effect
      src.seek(0)
      self.assertEqual(boxcutter.doFilter(src, dst3, False, ['TYPE=Exif','ITYPE=XML ']), 0)
      self.assertEqual(dst3.getvalue(), original)

  def testWildcards(self):
    with open(f'{TESTFILES}/pixel.jpg.jxl', 'rb') as src, \
         io.BytesIO() as dst1, io.BytesIO() as dst2, io.BytesIO() as dst3:
      self.assertEqual(boxcutter.doFilter(src, dst1, False, ['type~=*']), 0)
      self.assertEqual(dst1.getvalue(), b'')

      src.seek(0)
      self.assertEqual(boxcutter.doFilter(src, dst2, False, ['type~=????']), 0)
      self.assertEqual(dst2.getvalue(), b'')

      src.seek(0)
      self.assertEqual(boxcutter.doFilter(src, dst3, False,
                            ['TYPE=brob','itype~=[j ]xl*', 'type=jbrd', 'type~=*?**ra']), 0)
      self.assertEqual(dst3.getvalue(), b'\0\0\0\x14ftypjxl \0\0\0\0jxl ')

    awkwardBox = b'\0\0\0\0*?[]awkward'
    with io.BytesIO(awkwardBox) as src, \
         io.BytesIO() as dst, io.BytesIO() as dst2:
      src.seek(0)
      self.assertEqual(boxcutter.doFilter(src, dst, True, ['type=*?[]']), 0)
      self.assertEqual(dst.getvalue(), awkwardBox)

      src.seek(0)
      self.assertEqual(boxcutter.doFilter(src, dst2, True, ['type~=[*][?][[]]']), 0)
      self.assertEqual(dst2.getvalue(), awkwardBox)

  def testJxlTypes(self):
    with open(f'{TESTFILES}/pixel.jpg.jxl', 'rb') as src, \
         io.BytesIO() as dst1, io.BytesIO() as dst2:
      self.assertEqual(boxcutter.doFilter(src, dst1, True, ['@jxl']), 0)
      src.seek(0)
      self.assertEqual(boxcutter.doFilter(src, dst2, False,
                                          ['type=jbrd','type=Exif','type=xml ','type=xtra']), 0)
      self.assertEqual(dst1.getvalue(), dst2.getvalue())

    with open(f'{TESTFILES}/pixel.jpg.jxl', 'rb') as src, \
         io.BytesIO() as dst1, io.BytesIO() as dst2:
      self.assertEqual(boxcutter.doFilter(src, dst1, True, ['@JXL']), 0)
      src.seek(0)
      self.assertEqual(boxcutter.doFilter(src, dst2, False, ['type=xtra']), 0)
      self.assertEqual(dst1.getvalue(), dst2.getvalue())


  def testRemoveMulti(self):
    with open(f'{TESTFILES}/pixel-jxlp-8.jxl', 'rb') as src, \
         io.BytesIO() as dst:
      self.assertEqual(boxcutter.doFilter(src, dst, False, ['type=jxlp','i=0..0']), 0)
      self.assertEqual(dst.getvalue(), b'\0\0\0\x14ftypjxl \0\0\0\0jxl ')

class TestFilterWithCompression(unittest.TestCase):

  @unittest.skipIf(not boxcutter.HAVE_BROTLI, 'Brotli not supported')
  def testRemoveAndCompressProtectJxl(self):
    with open(f'{TESTFILES}/pixel.jpg.jxl', 'rb') as src, \
         io.BytesIO() as dst:
      compOpts = boxcutter.CompressionOpts(compressWhen=boxcutter.CompressionOpts.COMPRESS_ALWAYS)
      self.assertEqual(boxcutter.doFilter(src, dst, False, ['type=jxlp'], compOpts), 0)
      dst.seek(0)
      self.assertEqual(dst.read(12), boxcutter.JXL_CONTAINER_SIG)
      self.assertEqual(dst.read(8), b'\0\0\0\x14ftyp')
      dst.seek(12, io.SEEK_CUR)
      self.assertEqual(dst.read(8), b'\0\0\0\xc8jbrd')
      dst.seek(192, io.SEEK_CUR)
      self.assertEqual(dst.read(12), b'\0\0\0\xaabrobExif')
      dst.seek(158, io.SEEK_CUR)
      self.assertEqual(dst.read(12), b'\0\0\x02\xdcbrobxml ')
      dst.seek(720, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(8), b'brobxtra')

  @unittest.skipIf(not boxcutter.HAVE_BROTLI, 'Brotli not supported')
  def testRemoveAndCompressNoProtectJxl(self):
    with open(f'{TESTFILES}/pixel.jpg.jxl', 'rb') as src, \
         io.BytesIO() as dst:
      compOpts = boxcutter.CompressionOpts(compressWhen=boxcutter.CompressionOpts.COMPRESS_ALWAYS,
                                           protectJxl=False)
      self.assertEqual(boxcutter.doFilter(src, dst, False, ['type=jxlp'], compOpts), 0)
      dst.seek(0)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(8), b'brobJXL ')
      dst.seek(boxLen - 12, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(8), b'brobftyp')
      dst.seek(boxLen - 12, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(8), b'brobjbrd')
      dst.seek(boxLen - 12, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(8), b'brobExif')
      dst.seek(boxLen - 12, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(8), b'brobxml ')
      dst.seek(boxLen - 12, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(8), b'brobxtra')

  @unittest.skipIf(not boxcutter.HAVE_BROTLI, 'Brotli not supported')
  def testPassthroughCompressSpecific(self):
    with open(f'{TESTFILES}/pixel.jpg.jxl', 'rb') as src, \
         io.BytesIO() as dst:
      compOpts = boxcutter.CompressionOpts(compressWhen=boxcutter.CompressionOpts.COMPRESS_ALWAYS,
                 compressBoxes=boxcutter.boxspecStringsToBoxspecList(['type=Exif','i=6']),
                 protectJxl=False)
      self.assertEqual(boxcutter.doFilter(src, dst, True, None, compOpts), 0)
      dst.seek(0)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'JXL ')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'ftyp')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'jxlp')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'jbrd')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(8), b'brobExif')
      dst.seek(boxLen - 12, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(8), b'brobxml ')
      dst.seek(boxLen - 12, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(8), b'brobjxlp')
      dst.seek(boxLen - 12, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'xtra')


class TestFilterWithDecompression(unittest.TestCase):

  @unittest.skipIf(not boxcutter.HAVE_BROTLI, 'Brotli not supported')
  def testRemoveAndDecompress(self):
    with open(f'{TESTFILES}/pixel.jpg.jxl', 'rb') as src, \
         io.BytesIO() as dst:
      compOpts = boxcutter.CompressionOpts(decompressWhen=boxcutter.CompressionOpts.DECOMPRESS_ALWAYS)
      self.assertEqual(boxcutter.doFilter(src, dst, False, ['type=Exif'], compOpts), 0)
      dst.seek(0)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'JXL ')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'ftyp')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'jxlp')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'jbrd')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'xml ')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'jxlp')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'xtra')

  @unittest.skipIf(not boxcutter.HAVE_BROTLI, 'Brotli not supported')
  def testPassthroughCompressSpecific(self):
    with open(f'{TESTFILES}/pixel.jpg.jxl', 'rb') as src, \
         io.BytesIO() as dst:
      compOpts = boxcutter.CompressionOpts(decompressWhen=boxcutter.CompressionOpts.COMPRESS_ALWAYS,
                 decompressBoxes=boxcutter.boxspecStringsToBoxspecList(['type=xml ','i=0']))
      self.assertEqual(boxcutter.doFilter(src, dst, True, None, compOpts), 0)
      dst.seek(0)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'JXL ')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'ftyp')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'jxlp')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'jbrd')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(8), b'brobExif')
      dst.seek(boxLen - 12, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'xml ')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'jxlp')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'xtra')

class TestFilterWithCompressionAndDecompression(unittest.TestCase):

  @unittest.skipIf(not boxcutter.HAVE_BROTLI, 'Brotli not supported')
  def testRemoveAndCompressAndDecompress(self):
    with open(f'{TESTFILES}/pixel.jpg.jxl', 'rb') as src, \
         io.BytesIO() as dst:
      # Swap compressed / decompressed boxes
      compOpts = boxcutter.CompressionOpts(decompressWhen=boxcutter.CompressionOpts.DECOMPRESS_ALWAYS,
                                           compressWhen=boxcutter.CompressionOpts.COMPRESS_ALWAYS, protectJxl=False)
      self.assertEqual(boxcutter.doFilter(src, dst, False, ['type=Exif'], compOpts), 0)
      dst.seek(0)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(8), b'brobJXL ')
      dst.seek(boxLen - 12, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(8), b'brobftyp')
      dst.seek(boxLen - 12, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(8), b'brobjxlp')
      dst.seek(boxLen - 12, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(8), b'brobjbrd')
      dst.seek(boxLen - 12, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'xml ')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(8), b'brobjxlp')
      dst.seek(boxLen - 12, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(8), b'brobxtra')

    with open(f'{TESTFILES}/pixel.jpg.jxl', 'rb') as src, \
         io.BytesIO() as dst:
      # Swap compressed / decompressed boxes
      compOpts = boxcutter.CompressionOpts(decompressWhen=boxcutter.CompressionOpts.DECOMPRESS_ALWAYS,
                                           decompressBoxes=boxcutter.boxspecStringsToBoxspecList(['type=Exif']),
                                           compressWhen=boxcutter.CompressionOpts.COMPRESS_ALWAYS,
                                           compressBoxes=boxcutter.boxspecStringsToBoxspecList(['type=ftyp']),
                                           protectJxl=False)
      self.assertEqual(boxcutter.doFilter(src, dst, False, ['type=jxlp'], compOpts), 0)
      dst.seek(0)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'JXL ')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(8), b'brobftyp')
      dst.seek(boxLen - 12, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'jbrd')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'Exif')
      dst.seek(boxLen - 8, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(8), b'brobxml ')
      dst.seek(boxLen - 12, io.SEEK_CUR)
      (boxLen,) = struct.unpack('>I', dst.read(4))
      self.assertEqual(dst.read(4), b'xtra')

class TestIsValid4cc(unittest.TestCase):
  def testIsValid4cc(self):
    tests = ((b'abcd', True),
             (b' a0~', True),
             (b'a0~', False),
             (b'abc\x1F', False))
    for b, expect in tests:
      self.assertEqual(boxcutter.isValid4cc(b), expect, msg=f'Unexpected result for {b}')

class TestDecodeSize(unittest.TestCase):

  def testPlainNumber(self):
    for arg,expect in (('',       None),
                       (' ',      None),
                       ('0',      0),
                       ('-0',     0),
                       ('1',      1),
                       ('1 B',      1),
                       (' 1 ',    1),
                       (' -1 ',   -1),
                       ('k',      None),
                       ('0k',     0),
                       ('1k',     1000),
                       ('1ki',    1024),
                       (' 1 K ',  1000),
                       (' 1 KIB', 1024),
                       ('123kb',  123000),
                       ('123kbs', None),
                       ('2M',     2_000_000),
                       ('1.1M',   None),
                       ('2 Gi',   2147483648),
                       ('-2TB',   -2_000_000_000_000),
                       ):
      if expect is None:
        with self.assertRaises(ValueError, msg=arg):
          boxcutter.decodeSize(arg)
      else:
        self.assertEqual(boxcutter.decodeSize(arg), expect, msg=arg)

class TestList(unittest.TestCase):
  def testDoList(self):
    with io.StringIO() as capturedStdout:
      origStdout = sys.stdout
      try:
        sys.stdout = capturedStdout
        boxcutter.doList([f'{TESTFILES}/various-boxes.4cc'])
      finally:
        sys.stdout = origStdout
      self.assertEqual(capturedStdout.getvalue(), """\
seq off    len type
-------------------
[0] 0x000    8 AAAA
[1] 0x008   11 BBBB
[2] 0x013   21 CCCC *
[3] 0x028  +34 DDDD

  *Unnecessary use of extended box size wastes 8 bytes.
""")

    with io.StringIO() as capturedStdout:
      origStdout = sys.stdout
      try:
        sys.stdout = capturedStdout
        boxcutter.doList([f'{TESTFILES}/pixel-jxlc.jxl',
                          f'{TESTFILES}/pixel-jxlp-single.jxl'])
      finally:
        sys.stdout = origStdout
      self.assertEqual(capturedStdout.getvalue(), f"""\
{TESTFILES}/pixel-jxlc.jxl:
seq off    len type
-------------------
[0] 0x000   12 JXL 
[1] 0x00c   20 ftyp
[2] 0x020   27 jxlc

{TESTFILES}/pixel-jxlp-single.jxl:
seq off    len type
-------------------
[0] 0x000   12 JXL 
[1] 0x00c   20 ftyp
[2] 0x020   31 jxlp
""")

class TestMergeJxlps(unittest.TestCase):

  def testMerge(self):
    for before,after,codestream in (
      # Unchanged
      (b'',)*2 + (None,),
      (b'\0\0\0\x0cjxlp\x80\0\0\0',)*2 + (b'',),
      (b'\0\0\0\x08jxlc',)*2 + (b'',),
      (b'\0\0\0\x0djxlp\0\0\0\0y\0\0\0\x09ASDFx\0\0\0\x0djxlp\x80\0\0\x01z',)*2 + (b'yz',),
      (b'\0\0\0\x0djxlp\0\0\0\0y\0\0\0\x09ASDFx\0\0\0\x0djxlp\x80\0\0\x01z\0\0\0\x08GHJK',)*2 + (b'yz',),
      # All merged into 1
      (b'\0\0\0\x0cjxlp\0\0\0\0\0\0\0\x0cjxlp\x80\0\0\x01',
       b'\0\0\0\x0cjxlp\x80\0\0\0', b''),
      (b'\0\0\0\x0djxlp\0\0\0\0A\0\0\0\x0djxlp\x80\0\0\x01B',
       b'\0\0\0\x0ejxlp\x80\0\0\0AB', b'AB'),
      (b'\0\0\0\x0djxlp\0\0\0\0A\0\0\0\x0ejxlp\0\0\0\x01BC\0\0\0\x0fjxlp\x80\0\0\x02DEF', b'\0\0\0\x12jxlp\x80\0\0\0ABCDEF', b'ABCDEF'),
      # Single run at end
      (b'\0\0\0\x08XXXX\0\0\0\x0djxlp\0\0\0\0A\0\0\0\x0djxlp\x80\0\0\x01B',
       b'\0\0\0\x08XXXX\0\0\0\x0ejxlp\x80\0\0\0AB', b'AB'),
      # Single run at start
      (b'\0\0\0\x0djxlp\0\0\0\0A\0\0\0\x0ejxlp\0\0\0\x01BC\0\0\0\x0djxlp\x80\0\0\x02D\0\0\0\x09XXXXx',
       b'\0\0\0\x10jxlp\x80\0\0\0ABCD\0\0\0\x09XXXXx', b'ABCD'),
      # Single run in middle
      (b'\0\0\0\x0b1111one\0\0\0\x0djxlp\0\0\0\0y\0\0\0\x0djxlp\x80\0\0\x01z\0\0\0\x0b2222two',
       b'\0\0\0\x0b1111one\0\0\0\x0ejxlp\x80\0\0\0yz\0\0\0\x0b2222two', b'yz'),
      # With a gap
      (b'\0\0\0\x0djxlp\0\0\0\0A\0\0\0\x0b1111one\0\0\0\x0djxlp\0\0\0\x01B\0\0\0\x0djxlp\x80\0\0\x02C',
       b'\0\0\0\x0djxlp\0\0\0\0A\0\0\0\x0b1111one\0\0\0\x0ejxlp\x80\0\0\x01BC', b'ABC'),
      # Multiple runs
      (b'\0\0\0\x0djxlp\0\0\0\0A\0\0\0\x0djxlp\0\0\0\x01B\0\0\0\x0b1111one\0\0\0\x0djxlp\0\0\0\x02C\0\0\0\x0djxlp\x80\0\0\x03D',
       b'\0\0\0\x0ejxlp\0\0\0\0AB\0\0\0\x0b1111one\0\0\0\x0ejxlp\x80\0\0\x01CD', b'ABCD'),
      ):
      with io.BytesIO(before) as src, \
           io.BytesIO() as dst:
        self.assertEqual(boxcutter.mergeJxlps(src, dst), 0)
        self.assertEqual(dst.getvalue(), after, msg=dst.getvalue())

        # Make sure the extracted codestream is unchanged
        if len(before) > 0:
          with io.BytesIO() as container1, \
               io.BytesIO() as container2, \
               io.BytesIO() as codestream1, \
               io.BytesIO() as codestream2:
            container1.write(boxcutter.JXL_CONTAINER_SIG)
            container1.write(src.getvalue())
            container1.seek(0)
            container2.write(boxcutter.JXL_CONTAINER_SIG)
            container2.write(dst.getvalue())
            container2.seek(0)
            self.assertEqual(boxcutter.extractJxlCodestream(container1, codestream1,
                                                            False), 0)
            self.assertEqual(codestream1.getvalue(), codestream)
            self.assertEqual(boxcutter.extractJxlCodestream(container2, codestream2,
                                                            False), 0)
            self.assertEqual(codestream2.getvalue(), codestream)

  def testUnseekableOutput(self):
    with io.BytesIO(b'\0\0\0\x0cjxlp\x80\0\0\0') as src, \
         io.BytesIO() as dst:
      dst.seekable = lambda : False
      self.assertRaises(boxcutter.UnseekableOutputError, boxcutter.mergeJxlps, src, dst)

if __name__ == '__main__':
    unittest.main()

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
    self.assertEqual(boxcutter.getBoxCount(io.BytesIO()), 0)
    self.assertEqual(boxcutter.getBoxCount(io.BytesIO(), boxtype='JXL '), 0)

  def testCountRawJxl(self):
    with open(f'{TESTFILES}/pixel-raw.jxl', 'rb') as jxl:
      jxl.seek(0)
      self.assertEqual(boxcutter.getBoxCount(jxl), boxcutter.RAW_JXL)
      jxl.seek(0)
      self.assertEqual(boxcutter.getBoxCount(jxl, boxtype='JXL '), boxcutter.RAW_JXL)

  def testCountSimple(self):
    with open(f'{TESTFILES}/various-boxes.4cc', 'rb') as jxl:
      jxl.seek(0)
      self.assertEqual(boxcutter.getBoxCount(jxl), 4)
      jxl.seek(0)
      self.assertEqual(boxcutter.getBoxCount(jxl, 'BBBB'), 1)

  def testCountInvalid(self):
    with io.BytesIO(b'\0') as jxl:
      jxl.seek(0)
      self.assertEqual(boxcutter.getBoxCount(jxl), boxcutter.FAILED_PARSE)
    with io.BytesIO(b'\0\0\0\x09ABCD\0\0\0\x09EFGHx') as jxl:
      jxl.seek(0)
      self.assertEqual(boxcutter.getBoxCount(jxl), boxcutter.FAILED_PARSE)


class TestExtractCodestream(unittest.TestCase):

  def setUp(self):
    with open(f'{TESTFILES}/pixel-raw.jxl', 'rb') as raw:
      self.jxlcodestream = raw.read()

  def testJxlc(self):
    with open(f'{TESTFILES}/pixel-jxlc.jxl', 'rb') as jxl, \
         io.BytesIO() as result:
      self.assertEqual(boxcutter.extractJxlCodestream(jxl, result), 0)
      self.assertEqual(result.getvalue(), self.jxlcodestream)

  def testJxlp(self):
    for suffix in ('8','single','stupid'):
      fname = f'{TESTFILES}/pixel-jxlp-{suffix}.jxl'
      with open(fname, 'rb') as jxl, \
           io.BytesIO() as result:
        self.assertEqual(boxcutter.extractJxlCodestream(jxl, result), 0)
        self.assertEqual(result.getvalue(), self.jxlcodestream,
                         msg=f'Failed to get correct codestream from {fname}')

  def testJxlpWrongSequence(self):
    with open(f'{TESTFILES}/pixel-jxlp-badsequence.jxl', 'rb') as jxl, \
         io.BytesIO() as result:
      self.assertNotEqual(boxcutter.extractJxlCodestream(jxl, result), 0)


class TestWrapCodestream(unittest.TestCase):

  def setUp(self):
    with open(f'{TESTFILES}/pixel-raw.jxl', 'rb') as raw:
      self.jxlcodestream = raw.read()

  def testJxlc(self):
    with open(f'{TESTFILES}/pixel-jxlc.jxl', 'rb') as f:
      expect = f.read()

    with io.BytesIO(self.jxlcodestream) as src, \
         io.BytesIO() as dst:
      src.seek(0)
      self.assertEqual(boxcutter.addContainer(src, dst), 0)
      self.assertEqual(dst.getvalue(), expect)

    expect = boxcutter.JXL_CONTAINER_SIG + \
             b'\0\0\0\x14ftypjxl \0\0\0\0jxl ' + \
             b'\0\0\0\x09jxll\x0a' + \
             struct.pack('>I', 8 + len(self.jxlcodestream)) + b'jxlc' + \
             self.jxlcodestream

    with io.BytesIO(self.jxlcodestream) as src, \
         io.BytesIO() as dst:
      src.seek(0)
      self.assertEqual(boxcutter.addContainer(src, dst, jxll=10), 0)
      self.assertEqual(dst.getvalue(), expect)

  def testJxlpSensible(self):
    with open(f'{TESTFILES}/pixel-jxlp-8.jxl', 'rb') as f:
      expect = f.read()
    with io.BytesIO(self.jxlcodestream) as src, \
         io.BytesIO() as dst:
      src.seek(0)
      self.assertEqual(boxcutter.addContainer(src, dst, splits=[8]), 0)
      self.assertEqual(dst.getvalue(), expect)

  def testJxlpStupid(self):
    with open(f'{TESTFILES}/pixel-jxlp-single.jxl', 'rb') as f:
      expect = f.read()

    with io.BytesIO(self.jxlcodestream) as src, \
         io.BytesIO() as dst:
      src.seek(0)
      self.assertEqual(boxcutter.addContainer(src, dst, splits=[]), 0)
      self.assertEqual(dst.getvalue(), expect)

    with open(f'{TESTFILES}/pixel-jxlp-stupid.jxl', 'rb') as f:
      expect = f.read()

    with io.BytesIO(self.jxlcodestream) as src, \
         io.BytesIO() as dst:
      src.seek(0)
      self.assertEqual(boxcutter.addContainer(src, dst, splits=[0,8,9,11,9]), 0)
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
      self.assertNotEqual(boxcutter.doAddBoxes(src, dst, ['ab\tc='], 'utf-8'), 0)

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


class TestIsValid4cc(unittest.TestCase):
  def testIsValid4cc(self):
    tests = ((b'abcd', True),
             (b' a0~', True),
             (b'a0~', False),
             (b'abc\x1F', False))
    for b, expect in tests:
      self.assertEqual(boxcutter.isValid4cc(b), expect, msg=f'Unexpected result for {b}')

if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) Alistair Barrow. All rights reserved.
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file.

import io
import struct
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


if __name__ == '__main__':
    unittest.main()

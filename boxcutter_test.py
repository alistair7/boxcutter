#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) Alistair Barrow. All rights reserved.
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file.

import io
import unittest
import boxcutter

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


if __name__ == '__main__':
    unittest.main()

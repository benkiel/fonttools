from __future__ import print_function, division, absolute_import
from fontTools.misc.py23 import *
from fontTools.ttLib import TTFont
from fontTools.varLib.merger import VariationMerger
from fontTools.varLib.models import VariationModel
import difflib
import os
import shutil
import sys
import tempfile
import unittest


class VarLibMergerTest(unittest.TestCase):
    def __init__(self, methodName):
        unittest.TestCase.__init__(self, methodName)
        # Python 3 renamed assertRaisesRegexp to assertRaisesRegex,
        # and fires deprecation warnings if a program uses the old name.
        if not hasattr(self, "assertRaisesRegex"):
            self.assertRaisesRegex = self.assertRaisesRegexp

    def setUp(self):
        self.tempdir = None
        self.num_tempfiles = 0

    def tearDown(self):
        if self.tempdir:
            shutil.rmtree(self.tempdir)

    @staticmethod
    def get_test_input(test_file_or_folder):
        path, _ = os.path.split(__file__)
        return os.path.join(path, "data", test_file_or_folder)

    @staticmethod
    def get_test_output(test_file_or_folder):
        path, _ = os.path.split(__file__)
        return os.path.join(path, "data", "test_results", test_file_or_folder)

    @staticmethod
    def get_file_list(folder, suffix, prefix=''):
        all_files = os.listdir(folder)
        file_list = []
        for p in all_files:
            if p.startswith(prefix) and p.endswith(suffix):
                file_list.append(os.path.abspath(os.path.join(folder, p)))
        return file_list

    def temp_path(self, suffix):
        self.temp_dir()
        self.num_tempfiles += 1
        return os.path.join(self.tempdir,
                            "tmp%d%s" % (self.num_tempfiles, suffix))

    def temp_dir(self):
        if not self.tempdir:
            self.tempdir = tempfile.mkdtemp()

    def read_ttx(self, path):
        lines = []
        with open(path, "r", encoding="utf-8") as ttx:
            for line in ttx.readlines():
                # Elide ttFont attributes because ttLibVersion may change,
                # and use os-native line separators so we can run difflib.
                if line.startswith("<ttFont "):
                    lines.append("<ttFont>" + os.linesep)
                else:
                    lines.append(line.rstrip() + os.linesep)
        return lines

    def expect_ttx(self, font, expected_ttx, tables):
        path = self.temp_path('.ttx')
        font.saveXML(path, tables=tables)
        actual = self.read_ttx(path)
        expected = self.read_ttx(expected_ttx)
        if actual != expected:
            for line in difflib.unified_diff(
                    expected, actual, fromfile=expected_ttx, tofile=path):
                sys.stdout.write(line)
            self.fail("TTX output is different from expected")

    def check_ttx_dump(self, font, expected_ttf, tables, suffix):
        path = self.temp_path(suffix)
        font.save(path)
        path2 = self.temp_path('.ttx')
        font2 = TTFont(expected_ttf)
        font2.saveXML(path2, tables=tables)
        self.expect_ttx(TTFont(path), path2, tables)

# -----
# Tests
# -----

    def test_varlib_merger_fealib_gpos_small(self):
        """
        The GPOS tables of the input fonts were compiled with feaLib.
        """
        suffix = '.ttf'
        tables = ['GPOS']
        locations = [{'wght': 0}, {'wght': 1}]
        axis_tags = ['wght']
        ttf_dir = self.get_test_input('gpos_merge')
        ttf_paths = self.get_file_list(ttf_dir, suffix, 'fealib_small_')
        expected_file_name = 'MergerFeaLibGPOS_sm.ttf'

        varfont = TTFont(ttf_paths[0])
        master_fonts = [TTFont(ttf_path) for ttf_path in ttf_paths]
        model = VariationModel(locations)
        merger = VariationMerger(model, axis_tags, varfont)
        merger.mergeTables(varfont, master_fonts, tables)

        expected_ttf_path = self.get_test_output(expected_file_name)
        self.check_ttx_dump(varfont, expected_ttf_path, tables, suffix)

    def test_varlib_merger_fealib_gpos_large(self):
        """
        The GPOS tables of the input fonts were compiled with feaLib
        and required fixes for OTLOffsetOverflowError.
        """
        suffix = '.ttf'
        tables = ['GPOS']
        locations = [{'wght': 0}, {'wght': 1}]
        axis_tags = ['wght']
        ttf_dir = self.get_test_input('gpos_merge')
        ttf_paths = self.get_file_list(ttf_dir, suffix, 'fealib_large_')
        expected_file_name = 'MergerFeaLibGPOS_lg.ttf'

        varfont = TTFont(ttf_paths[0])
        master_fonts = [TTFont(ttf_path) for ttf_path in ttf_paths]
        model = VariationModel(locations)
        merger = VariationMerger(model, axis_tags, varfont)
        merger.mergeTables(varfont, master_fonts, tables)

        expected_ttf_path = self.get_test_output(expected_file_name)
        self.check_ttx_dump(varfont, expected_ttf_path, tables, suffix)


if __name__ == "__main__":
    sys.exit(unittest.main())

# Copyright (c) 2015 Spotify AB
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under
# the License.

import sys
import subprocess
import os
import shutil
import tempfile
import re
from unittest import TestCase
from pyschema import Record, Text, Integer, no_auto_store, Enum, SubRecord
from pyschema.source_generation import (
    to_python_source,
    classes_source,
    SourceGenerationError,
    to_python_package,
    header_source
)
from pyschema.types import SELF
from . import source_generation_helpers


@no_auto_store()
class FooRecord(Record):
    _namespace = "my.foo.bar"
    field_1 = Text()
    a = 5
    bar = Integer()


class TestSourceConversion(TestCase):
    correct = (
        "class FooRecord(pyschema.Record):\n"
        "    # WARNING: This class was generated by pyschema.to_python_source\n"
        "    # there is a risk that any modification made to this class will be overwritten\n"
        "    _namespace = \'my.foo.bar\'\n"
        "    field_1 = Text(nullable=True, default=None)\n"
        "    bar = Integer(size=8, nullable=True, default=None)\n"
    )

    def foo_record_test(self):
        src = classes_source([FooRecord], indent=" " * 4)
        self.assertEqual(
            src,
            self.correct,
            msg="Incorrect definition:\n\"\"\"\n{0}\"\"\"\nShould have been:\n\"\"\"\n{1}\"\"\"".format(src, self.correct)
        )


class NonZeroExit(Exception):
    # custom error since check_output doesn't exist in python 2.6
    def __init__(self, code, output):
        self.message = "Python interpreter exited with status {0}. Error output:\n{1}".format(code, output)

    def __str__(self):
        return self.message


def call_python(source):
    p = subprocess.Popen([sys.executable, "-c", source], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    p.wait()

    if p.returncode:
        raise NonZeroExit(p.returncode, p.stdout.read())


class AutoTest(object):
    schema_classes = []

    def test_parsable(self):
        src = to_python_source(self.schema_classes)
        assertion_footer = "\n".join(
            "assert {0}".format(schema._schema_name)
            for schema in self.schema_classes
        )
        try:
            call_python(src + '\n' + assertion_footer)
        except NonZeroExit as e:
            self.fail("Problem when parsing:\n\n{0}\n\n{1}".format(src, e.message))


class TestFooRecord(AutoTest, TestCase):
    schema_classes = [FooRecord]


@no_auto_store()
class EnumRecord(Record):
    e = Enum(["HELLO", "GOODBYE"])


class TestEnumRecord(AutoTest, TestCase):
    schema_classes = [EnumRecord]


class DependentRecords(AutoTest, TestCase):
    schema_classes = [source_generation_helpers.A, source_generation_helpers.B]


class DependentRecordsOther(AutoTest, TestCase):
    schema_classes = [source_generation_helpers.B, source_generation_helpers.A]


@no_auto_store()
class Child(Record):
    a = Integer()


@no_auto_store()
class Parent(Record):
    child = SubRecord(Child)


class TestSubRecord(TestCase):
    correct = """class Child(pyschema.Record):
    # WARNING: This class was generated by pyschema.to_python_source
    # there is a risk that any modification made to this class will be overwritten
    a = Integer(size=8, nullable=True, default=None)


class Parent(pyschema.Record):
    # WARNING: This class was generated by pyschema.to_python_source
    # there is a risk that any modification made to this class will be overwritten
    child = SubRecord(schema=Child, nullable=True, default=None)
"""

    def test_implicit_inclusion(self):
        src = classes_source([Parent])

        self.assertEquals(
            src,
            self.correct,
            msg="Incorrect definition:\n\"\"\"\n{0}\"\"\"\nShould have been:\n\"\"\"\n{1}\"\"\"".format(src, self.correct)
        )


@no_auto_store()
class SelfReferencingRecord(Record):
    other_record = SubRecord(SELF)


class TestSelfReference(TestCase):
    """Circular references, including self references, aren't supported at this time"""
    def test_circular_dependency_triggers_error(self):
        self.assertRaises(SourceGenerationError, classes_source, [SelfReferencingRecord])


@no_auto_store()
class ChildWithOwnNameSpace(Record):
    _namespace = "test.pyschema_test_child"
    a = Integer()


@no_auto_store()
class ChildWithSameNamespace(Record):
    _namespace = "pyschema_test_parent"


@no_auto_store()
class ParentWithNameSpace(Record):
    _namespace = "pyschema_test_parent"
    child = SubRecord(ChildWithOwnNameSpace)
    other = SubRecord(ChildWithSameNamespace)


class TestPythonPackageGeneration(TestCase):
    def setUp(self):
        self.tmp_path = tempfile.mkdtemp()

    def get_file_content(self, relative_path):
        return open(os.path.join(self.tmp_path, relative_path)).read()

    def tearDown(self):
        shutil.rmtree(self.tmp_path)

    def test_package_generation_no_namespace(self):
        to_python_package([Parent], self.tmp_path)
        src = self.get_file_content("__init__.py")
        expected_src = header_source() + "\n" + TestSubRecord.correct
        self.assertEquals(src, expected_src)

    def test_package_generation_namespace(self):
        to_python_package([FooRecord], self.tmp_path)
        src = self.get_file_content("my/foo/bar.py")
        expected_src = header_source() + "\n" + TestSourceConversion.correct
        self.assertEquals(src, expected_src)
        #TODO, verify __init__ files

    def assertContainsOnlyClasses(self, code_string, class_names):
        matches = re.finditer(r"class (\w+)\(", code_string)
        found_declarations = set([m.group(1) for m in matches])
        self.assertEquals(found_declarations, set(class_names))

    def test_multiple_namespaces(self):
        to_python_package([ParentWithNameSpace], self.tmp_path)
        src1 = self.get_file_content("pyschema_test_parent.py")
        self.assertContainsOnlyClasses(src1, ["ParentWithNameSpace", "ChildWithSameNamespace"])
        src2 = self.get_file_content("test/pyschema_test_child.py")
        self.assertContainsOnlyClasses(src2, ["ChildWithOwnNameSpace"])

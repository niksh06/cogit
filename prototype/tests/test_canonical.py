import unittest

from tests.helpers import *  # noqa: F401,F403  (sys.path setup)
from cogit.canonical import canonical_json, parse_json
from cogit.errors import UserError


class CanonicalJsonTests(unittest.TestCase):
    def test_keys_sorted_by_code_point(self):
        self.assertEqual(canonical_json({"b": 1, "a": 2, "A": 3}), '{"A":3,"a":2,"b":1}')

    def test_no_insignificant_whitespace(self):
        self.assertEqual(canonical_json({"a": [1, 2], "b": {"c": True}}), '{"a":[1,2],"b":{"c":true}}')

    def test_minimal_escaping_and_raw_utf8(self):
        self.assertEqual(canonical_json({"k": 'a"b\\c\n\t'}), '{"k":"a\\"b\\\\c\\n\\t"}')
        self.assertEqual(canonical_json({"k": "жест"}), '{"k":"жест"}')
        self.assertEqual(canonical_json({"k": "\x01"}), '{"k":"\\u0001"}')

    def test_float_rejected(self):
        with self.assertRaises(UserError):
            canonical_json({"confidence": 0.92})

    def test_unsafe_integer_rejected(self):
        with self.assertRaises(UserError):
            canonical_json({"n": 2**53})
        canonical_json({"n": 2**53 - 1})  # boundary is allowed

    def test_non_string_key_rejected(self):
        with self.assertRaises(UserError):
            canonical_json({1: "x"})

    def test_same_value_same_bytes_regardless_of_insertion_order(self):
        a = {"x": 1, "y": [3, 4], "z": {"k": "v"}}
        b = {"z": {"k": "v"}, "y": [3, 4], "x": 1}
        self.assertEqual(canonical_json(a), canonical_json(b))

    def test_parse_json_rejects_floats(self):
        with self.assertRaises(UserError):
            parse_json('{"confidence": 0.92}')
        self.assertEqual(parse_json('{"n": 92}'), {"n": 92})


if __name__ == "__main__":
    unittest.main()

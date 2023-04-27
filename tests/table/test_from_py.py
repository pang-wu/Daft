from __future__ import annotations

import datetime
import itertools

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pac
import pytest
from ray.data.extensions import ArrowTensorArray, ArrowTensorType

from daft import DataType
from daft.series import Series
from daft.table import Table

PYTHON_TYPE_ARRAYS = {
    "int": [1, 2],
    "float": [1.0, 2.0],
    "bool": [True, False],
    "str": ["foo", "bar"],
    "binary": [b"foo", b"bar"],
    "date": [datetime.date.today(), datetime.date.today()],
    "list": [[1, 2], [3]],
    "struct": [{"a": 1, "b": 2.0}, {"b": 3.0}],
    "tensor": list(np.array([[[1, 2], [3, 4]], [[5, 6], [7, 8]]])),
    "null": [None, None],
}


INFERRED_TYPES = {
    "int": DataType.int64(),
    "float": DataType.float64(),
    "bool": DataType.bool(),
    "str": DataType.string(),
    "binary": DataType.binary(),
    "date": DataType.date(),
    "list": DataType.list("item", DataType.int64()),
    "struct": DataType.struct({"a": DataType.int64(), "b": DataType.float64()}),
    "tensor": DataType.python(),
    "null": DataType.null(),
}


ROUNDTRIP_TYPES = {
    "int": pa.int64(),
    "float": pa.float64(),
    "bool": pa.bool_(),
    "str": pa.large_string(),
    "binary": pa.large_binary(),
    "date": pa.date32(),
    "list": pa.large_list(pa.int64()),
    "struct": pa.struct({"a": pa.int64(), "b": pa.float64()}),
    "tensor": ArrowTensorType(shape=(2, 2), dtype=pa.int64()),
    "null": pa.null(),
}


ARROW_TYPE_ARRAYS = {
    "int8": pa.array(PYTHON_TYPE_ARRAYS["int"], pa.int8()),
    "int16": pa.array(PYTHON_TYPE_ARRAYS["int"], pa.int16()),
    "int32": pa.array(PYTHON_TYPE_ARRAYS["int"], pa.int32()),
    "int64": pa.array(PYTHON_TYPE_ARRAYS["int"], pa.int64()),
    "uint8": pa.array(PYTHON_TYPE_ARRAYS["int"], pa.uint8()),
    "uint16": pa.array(PYTHON_TYPE_ARRAYS["int"], pa.uint16()),
    "uint32": pa.array(PYTHON_TYPE_ARRAYS["int"], pa.uint32()),
    "uint64": pa.array(PYTHON_TYPE_ARRAYS["int"], pa.uint64()),
    "float32": pa.array(PYTHON_TYPE_ARRAYS["float"], pa.float32()),
    "float64": pa.array(PYTHON_TYPE_ARRAYS["float"], pa.float64()),
    "string": pa.array(PYTHON_TYPE_ARRAYS["str"], pa.string()),
    "binary": pa.array(PYTHON_TYPE_ARRAYS["binary"], pa.binary()),
    "boolean": pa.array(PYTHON_TYPE_ARRAYS["bool"], pa.bool_()),
    "date32": pa.array(PYTHON_TYPE_ARRAYS["date"], pa.date32()),
    "list": pa.array(PYTHON_TYPE_ARRAYS["list"], pa.list_(pa.int64())),
    "fixed_size_list": pa.array([[1, 2], [3, 4]], pa.list_(pa.int64(), 2)),
    "struct": pa.array(PYTHON_TYPE_ARRAYS["struct"], pa.struct([("a", pa.int64()), ("b", pa.float64())])),
    # TODO(Clark): Uncomment once extension type support has been added.
    # "tensor": ArrowTensorArray.from_numpy(PYTHON_TYPE_ARRAYS["tensor"]),
    "null": pa.array(PYTHON_TYPE_ARRAYS["null"], pa.null()),
}


ARROW_ROUNDTRIP_TYPES = {
    "int8": pa.int8(),
    "int16": pa.int16(),
    "int32": pa.int32(),
    "int64": pa.int64(),
    "uint8": pa.uint8(),
    "uint16": pa.uint16(),
    "uint32": pa.uint32(),
    "uint64": pa.uint64(),
    "float32": pa.float32(),
    "float64": pa.float64(),
    "string": pa.large_string(),
    "binary": pa.large_binary(),
    "boolean": pa.bool_(),
    "date32": pa.date32(),
    "list": pa.large_list(pa.int64()),
    "fixed_size_list": pa.list_(pa.int64(), 2),
    "struct": pa.struct([("a", pa.int64()), ("b", pa.float64())]),
    # TODO(Clark): Uncomment once extension type support has been added.
    # "tensor": ArrowTensorType(shape=(2, 2), dtype=pa.int64()),
    "null": pa.null(),
}


def test_from_pydict_roundtrip() -> None:
    table = Table.from_pydict(PYTHON_TYPE_ARRAYS)
    assert len(table) == 2
    assert set(table.column_names()) == set(PYTHON_TYPE_ARRAYS.keys())
    for field in table.schema():
        assert field.dtype == INFERRED_TYPES[field.name]
    schema = pa.schema(ROUNDTRIP_TYPES)
    arrs = {}
    for col_name, col in PYTHON_TYPE_ARRAYS.items():
        if col_name == "tensor":
            arrs[col_name] = ArrowTensorArray.from_numpy(col)
        else:
            arrs[col_name] = pa.array(col, type=schema.field(col_name).type)
    expected_table = pa.table(arrs, schema=schema)
    assert table.to_arrow() == expected_table


def test_from_pydict_arrow_roundtrip() -> None:
    table = Table.from_pydict(ARROW_TYPE_ARRAYS)
    assert len(table) == 2
    assert set(table.column_names()) == set(ARROW_TYPE_ARRAYS.keys())
    for field in table.schema():
        assert field.dtype == DataType.from_arrow_type(ARROW_TYPE_ARRAYS[field.name].type)
    expected_table = pa.table(ARROW_TYPE_ARRAYS).cast(pa.schema(ARROW_ROUNDTRIP_TYPES))
    assert table.to_arrow() == expected_table


def test_from_arrow_roundtrip() -> None:
    pa_table = pa.table(ARROW_TYPE_ARRAYS)
    table = Table.from_arrow(pa_table)
    assert len(table) == 2
    assert set(table.column_names()) == set(ARROW_TYPE_ARRAYS.keys())
    for field in table.schema():
        assert field.dtype == DataType.from_arrow_type(ARROW_TYPE_ARRAYS[field.name].type)
    expected_table = pa.table(ARROW_TYPE_ARRAYS).cast(pa.schema(ARROW_ROUNDTRIP_TYPES))
    assert table.to_arrow() == expected_table


def test_from_pandas_roundtrip() -> None:
    # TODO(Clark): Remove struct column until our .to_pandas() representation is
    # consistent with pyarrow's.
    # Our struct representation, when converted to pandas, currently materializes the Nones
    # while pyarrow's does not.
    data = {col_name: col for col_name, col in PYTHON_TYPE_ARRAYS.items() if col_name != "struct"}
    df = pd.DataFrame(data)
    table = Table.from_pandas(df)
    assert len(table) == 2
    assert set(table.column_names()) == set(data.keys())
    for field in table.schema():
        assert field.dtype == INFERRED_TYPES[field.name]
    # pyarrow --> pandas doesn't preserve the datetime type for the "date" column, so we need to
    # convert it before the comparison.
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[s]")
    pd.testing.assert_frame_equal(table.to_pandas(), df)


def test_from_pydict_list() -> None:
    daft_table = Table.from_pydict({"a": [1, 2, 3]})
    assert "a" in daft_table.column_names()
    assert daft_table.to_arrow()["a"].combine_chunks() == pa.array([1, 2, 3], type=pa.int64())


def test_from_pydict_np() -> None:
    daft_table = Table.from_pydict({"a": np.array([1, 2, 3], dtype=np.int64)})
    assert "a" in daft_table.column_names()
    assert daft_table.to_arrow()["a"].combine_chunks() == pa.array([1, 2, 3], type=pa.int64())


def test_from_pydict_arrow() -> None:
    daft_table = Table.from_pydict({"a": pa.array([1, 2, 3], type=pa.int8())})
    assert "a" in daft_table.column_names()
    assert daft_table.to_arrow()["a"].combine_chunks() == pa.array([1, 2, 3], type=pa.int8())


@pytest.mark.parametrize("list_type", [pa.list_, pa.large_list])
def test_from_pydict_arrow_list_array(list_type) -> None:
    arrow_arr = pa.array([["a", "b"], ["c"], None, [None, "d", "e"]], list_type(pa.string()))
    daft_table = Table.from_pydict({"a": arrow_arr})
    assert "a" in daft_table.column_names()
    # Perform expected Daft cast, where the outer list array is cast to a large list array
    # (if the outer list array wasn't already a large list in the first place), and
    # the inner string array is cast to a large string array.
    expected = arrow_arr.cast(pa.large_list(pa.large_string()))
    assert daft_table.to_arrow()["a"].combine_chunks() == expected


def test_from_pydict_arrow_fixed_size_list_array() -> None:
    arrow_arr = pa.array([["a", "b"], ["c", "d"], None, [None, "e"]], pa.list_(pa.string(), 2))
    daft_table = Table.from_pydict({"a": arrow_arr})
    assert "a" in daft_table.column_names()
    # Perform expected Daft cast, where the inner string array is cast to a large string array.
    expected = arrow_arr.cast(pa.list_(pa.large_string(), 2))
    assert daft_table.to_arrow()["a"].combine_chunks() == expected


def test_from_pydict_arrow_struct_array() -> None:
    arrow_arr = pa.array([{"a": "foo", "b": "bar"}, {"b": "baz", "c": "quux"}])
    daft_table = Table.from_pydict({"a": arrow_arr})
    assert "a" in daft_table.column_names()
    # Perform expected Daft cast, where the inner string array is cast to a large string array.
    expected = arrow_arr.cast(pa.struct([("a", pa.large_string()), ("b", pa.large_string()), ("c", pa.large_string())]))
    assert daft_table.to_arrow()["a"].combine_chunks() == expected


def test_from_pydict_arrow_deeply_nested() -> None:
    # Test a struct of lists of struct of lists of strings.
    arrow_arr = pa.array([{"a": [{"b": ["foo", "bar"]}]}, {"a": [{"b": ["baz", "quux"]}]}])
    daft_table = Table.from_pydict({"a": arrow_arr})
    assert "a" in daft_table.column_names()
    # Perform the expected Daft cast, where each list array is cast to a large list array and
    # the string array is cast to a large string array.
    expected = arrow_arr.cast(pa.struct([("a", pa.large_list(pa.struct([("b", pa.large_list(pa.large_string()))])))]))
    assert daft_table.to_arrow()["a"].combine_chunks() == expected


@pytest.mark.parametrize(
    "data,out_dtype",
    [
        (pa.array([1, 2, None, 4], type=pa.int64()), pa.int64()),
        (pa.array(["a", "b", None, "d"], type=pa.string()), pa.large_string()),
        (pa.array([b"a", b"b", None, b"d"], type=pa.binary()), pa.large_binary()),
        (pa.array([[1, 2], [3], None, [None, 4]], pa.list_(pa.int64())), pa.large_list(pa.int64())),
        (pa.array([[1, 2], [3, 4], None, [None, 6]], pa.list_(pa.int64(), 2)), pa.list_(pa.int64(), 2)),
        (
            pa.array([{"a": 1, "b": 2}, {"b": 3, "c": 4}, None, {"a": 5, "c": 6}]),
            pa.struct([("a", pa.int64()), ("b", pa.int64()), ("c", pa.int64())]),
        ),
    ],
)
@pytest.mark.parametrize("chunked", [False, True])
def test_from_pydict_arrow_with_nulls_roundtrip(data, out_dtype, chunked) -> None:
    if chunked:
        data = pa.chunked_array(data)
    daft_table = Table.from_pydict({"a": data})
    assert "a" in daft_table.column_names()
    if chunked:
        data = data.combine_chunks()
    assert daft_table.to_arrow()["a"].combine_chunks() == pac.cast(data, out_dtype)


@pytest.mark.parametrize(
    "data,out_dtype",
    [
        # Full data.
        (pa.array([1, 2, 3, 4], type=pa.int64()), pa.int64()),
        (pa.array(["a", "b", "c", "d"], type=pa.string()), pa.large_string()),
        (pa.array([b"a", b"b", b"c", b"d"], type=pa.binary()), pa.large_binary()),
        (pa.array([[1, 2], [3], [4, 5, 6], [None, 7]], pa.list_(pa.int64())), pa.large_list(pa.int64())),
        (pa.array([[1, 2], [3, None], [4, 5], [None, 6]], pa.list_(pa.int64(), 2)), pa.list_(pa.int64(), 2)),
        (
            pa.array([{"a": 1, "b": 2}, {"b": 3, "c": 4}, {"a": 5}, {"a": 6, "c": 7}]),
            pa.struct([("a", pa.int64()), ("b", pa.int64()), ("c", pa.int64())]),
        ),
        # Contains nulls.
        (pa.array([1, 2, None, 4], type=pa.int64()), pa.int64()),
        (pa.array(["a", "b", None, "d"], type=pa.string()), pa.large_string()),
        (pa.array([b"a", b"b", None, b"d"], type=pa.binary()), pa.large_binary()),
        (pa.array([[1, 2], [3], None, [None, 4]], pa.list_(pa.int64())), pa.large_list(pa.int64())),
        (pa.array([[1, 2], [3, 4], None, [None, 6]], pa.list_(pa.int64(), 2)), pa.list_(pa.int64(), 2)),
        (
            pa.array([{"a": 1, "b": 2}, {"b": 3, "c": 4}, None, {"a": 5, "c": 6}]),
            pa.struct([("a", pa.int64()), ("b", pa.int64()), ("c", pa.int64())]),
        ),
    ],
)
@pytest.mark.parametrize("chunked", [False, True])
@pytest.mark.parametrize("slice_", list(itertools.combinations(range(4), 2)))
def test_from_pydict_arrow_sliced_roundtrip(data, out_dtype, chunked, slice_) -> None:
    offset, end = slice_
    length = end - offset
    sliced_data = data.slice(offset, length)
    if chunked:
        sliced_data = pa.chunked_array(sliced_data)
    daft_table = Table.from_pydict({"a": sliced_data})
    assert "a" in daft_table.column_names()
    if chunked:
        sliced_data = sliced_data.combine_chunks()
    assert daft_table.to_arrow()["a"].combine_chunks() == pac.cast(sliced_data, out_dtype)


def test_from_pydict_series() -> None:
    daft_table = Table.from_pydict({"a": Series.from_arrow(pa.array([1, 2, 3], type=pa.int8()))})
    assert "a" in daft_table.column_names()
    assert daft_table.to_arrow()["a"].combine_chunks() == pa.array([1, 2, 3], type=pa.int8())


@pytest.mark.parametrize(
    "data,out_dtype",
    [
        # Full data.
        (pa.array([1, 2, 3, 4], type=pa.int64()), pa.int64()),
        (pa.array(["a", "b", "c", "d"], type=pa.string()), pa.large_string()),
        (pa.array([b"a", b"b", b"c", b"d"], type=pa.binary()), pa.large_binary()),
        (pa.array([[1, 2], [3], [4, 5, 6], [None, 7]], pa.list_(pa.int64())), pa.large_list(pa.int64())),
        (pa.array([[1, 2], [3, None], [4, 5], [None, 6]], pa.list_(pa.int64(), 2)), pa.list_(pa.int64(), 2)),
        (
            pa.array([{"a": 1, "b": 2}, {"b": 3, "c": 4}, {"a": 5}, {"a": 6, "c": 7}]),
            pa.struct([("a", pa.int64()), ("b", pa.int64()), ("c", pa.int64())]),
        ),
        # Contains nulls.
        (pa.array([1, 2, None, 4], type=pa.int64()), pa.int64()),
        (pa.array(["a", "b", None, "d"], type=pa.string()), pa.large_string()),
        (pa.array([b"a", b"b", None, b"d"], type=pa.binary()), pa.large_binary()),
        (pa.array([[1, 2], [3], None, [None, 4]], pa.list_(pa.int64())), pa.large_list(pa.int64())),
        (pa.array([[1, 2], [3, 4], None, [None, 6]], pa.list_(pa.int64(), 2)), pa.list_(pa.int64(), 2)),
        (
            pa.array([{"a": 1, "b": 2}, {"b": 3, "c": 4}, None, {"a": 5, "c": 6}]),
            pa.struct([("a", pa.int64()), ("b", pa.int64()), ("c", pa.int64())]),
        ),
    ],
)
@pytest.mark.parametrize("slice_", list(itertools.combinations(range(4), 2)))
def test_from_arrow_sliced_roundtrip(data, out_dtype, slice_) -> None:
    offset, end = slice_
    length = end - offset
    sliced_data = data.slice(offset, length)
    daft_table = Table.from_arrow(pa.table({"a": sliced_data}))
    assert "a" in daft_table.column_names()
    assert daft_table.to_arrow()["a"].combine_chunks() == pac.cast(sliced_data, out_dtype)


@pytest.mark.parametrize("list_type", [pa.list_, pa.large_list])
def test_from_arrow_list_array(list_type) -> None:
    arrow_arr = pa.array([["a", "b"], ["c"], None, [None, "d", "e"]], list_type(pa.string()))
    daft_table = Table.from_arrow(pa.table({"a": arrow_arr}))
    assert "a" in daft_table.column_names()
    # Perform expected Daft cast, where the outer list array is cast to a large list array
    # (if the outer list array wasn't already a large list in the first place), and
    # the inner string array is cast to a large string array.
    expected = arrow_arr.cast(pa.large_list(pa.large_string()))
    assert daft_table.to_arrow()["a"].combine_chunks() == expected


def test_from_arrow_fixed_size_list_array() -> None:
    arrow_arr = pa.array([["a", "b"], ["c", "d"], None, [None, "e"]], pa.list_(pa.string(), 2))
    daft_table = Table.from_arrow(pa.table({"a": arrow_arr}))
    assert "a" in daft_table.column_names()
    # Perform expected Daft cast, where the inner string array is cast to a large string array.
    expected = arrow_arr.cast(pa.list_(pa.large_string(), 2))
    assert daft_table.to_arrow()["a"].combine_chunks() == expected


def test_from_arrow_struct_array() -> None:
    arrow_arr = pa.array([{"a": "foo", "b": "bar"}, {"b": "baz", "c": "quux"}])
    daft_table = Table.from_arrow(pa.table({"a": arrow_arr}))
    assert "a" in daft_table.column_names()
    # Perform expected Daft cast, where the inner string array is cast to a large string array.
    expected = arrow_arr.cast(pa.struct([("a", pa.large_string()), ("b", pa.large_string()), ("c", pa.large_string())]))
    assert daft_table.to_arrow()["a"].combine_chunks() == expected


def test_from_arrow_deeply_nested() -> None:
    # Test a struct of lists of struct of lists of strings.
    arrow_arr = pa.array([{"a": [{"b": ["foo", "bar"]}]}, {"a": [{"b": ["baz", "quux"]}]}])
    daft_table = Table.from_arrow(pa.table({"a": arrow_arr}))
    assert "a" in daft_table.column_names()
    # Perform the expected Daft cast, where each list array is cast to a large list array and
    # the string array is cast to a large string array.
    expected = arrow_arr.cast(pa.struct([("a", pa.large_list(pa.struct([("b", pa.large_list(pa.large_string()))])))]))
    assert daft_table.to_arrow()["a"].combine_chunks() == expected


def test_from_pydict_bad_input() -> None:
    with pytest.raises(ValueError, match="Mismatch in Series lengths"):
        Table.from_pydict({"a": [1, 2, 3, 4], "b": [5, 6, 7]})


def test_pyobjects_roundtrip() -> None:
    o0, o1 = object(), object()
    table = Table.from_pydict({"objs": [o0, o1, None]})
    objs = table.to_pydict()["objs"]
    assert objs[0] is o0
    assert objs[1] is o1
    assert objs[2] is None
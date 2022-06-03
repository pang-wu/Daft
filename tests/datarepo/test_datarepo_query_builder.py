import pytest

from daft.dataclasses import dataclass
from daft.datarepo.log import DaftLakeLog
from daft.datarepo.query.definitions import QueryColumn, FilterPredicate
from daft.datarepo.query import stages
from daft.datarepo.datarepo import DataRepo

FAKE_DATAREPO_ID = "mydatarepo"
FAKE_DATAREPO_PATH = f"file:///tmp/fake_{FAKE_DATAREPO_ID}_path"


@dataclass
class MyFakeDataclass:
    foo: str


@pytest.fixture(scope="function")
def fake_datarepo() -> DataRepo:
    # TODO(jaychia): Use Datarepo client here instead once API stabilizes
    daft_lake_log = DaftLakeLog(FAKE_DATAREPO_PATH)
    return DataRepo(daft_lake_log)


def test_query_select_star(fake_datarepo: DataRepo) -> None:
    q = fake_datarepo.query(MyFakeDataclass)
    expected_stages = [
        stages.GetDatarepoStage(daft_lake_log=fake_datarepo._log, dtype=MyFakeDataclass, read_limit=None)
    ]
    assert len(q._query_tree.nodes()) == 1
    assert [k for k in q._query_tree.nodes()][0] == q._root
    assert [v["stage"] for _, v in q._query_tree.nodes().items()] == expected_stages


def test_query_limit(fake_datarepo: DataRepo) -> None:
    limit = 10
    q = fake_datarepo.query(MyFakeDataclass).limit(limit)
    expected_stages = [
        stages.GetDatarepoStage(daft_lake_log=fake_datarepo._log, dtype=MyFakeDataclass, read_limit=None),
        stages.LimitStage(limit=limit),
    ]
    assert len(q._query_tree.nodes()) == 2
    assert [k for k in q._query_tree.nodes()][-1] == q._root
    assert [v["stage"] for _, v in q._query_tree.nodes().items()] == expected_stages


def test_query_limit_optimization_simple(fake_datarepo: DataRepo) -> None:
    limit = 10
    q = fake_datarepo.query(MyFakeDataclass).limit(limit)
    optimized_tree, root = q._optimize_query_tree()
    expected_optimized_read_stage = stages.GetDatarepoStage(
        daft_lake_log=fake_datarepo._log, dtype=MyFakeDataclass, read_limit=limit
    )
    assert len(optimized_tree.nodes()) == 1
    assert [v for _, v in optimized_tree.nodes().items()][0]["stage"] == expected_optimized_read_stage


def test_query_limit_optimization_interleaved(fake_datarepo: DataRepo) -> None:
    limit = 10
    pred = FilterPredicate(left="id", comparator=">", right="5")
    f = lambda x: 1
    q = (
        fake_datarepo.query(MyFakeDataclass)
        .limit(limit)
        .filter(predicate=pred)
        .limit(limit + 2)
        .filter(predicate=pred)
        .limit(limit + 1)
        .apply(f, QueryColumn(name="foo"))
        .limit(limit)
    )
    optimized_tree, root = q._optimize_query_tree()
    expected_optimized_stages = [
        stages.GetDatarepoStage(daft_lake_log=fake_datarepo._log, dtype=MyFakeDataclass, read_limit=limit),
        # TODO: the filter stages will likely be pushed down to GetDatarepoStage as well in the near future
        stages.FilterStage(predicate=pred),
        stages.FilterStage(predicate=pred),
        stages.ApplyStage(f=f, args=(QueryColumn(name="foo"),), kwargs={}),
    ]
    assert [v["stage"] for _, v in optimized_tree.nodes().items()] == expected_optimized_stages


def test_query_limit_optimization_min_limits(fake_datarepo: DataRepo) -> None:
    limit = 10
    for q in [
        fake_datarepo.query(MyFakeDataclass).limit(limit).limit(limit + 10),
        fake_datarepo.query(MyFakeDataclass).limit(limit + 10).limit(limit),
        fake_datarepo.query(MyFakeDataclass).limit(limit).limit(limit),
    ]:
        optimized_tree, root = q._optimize_query_tree()
        expected_optimized_read_stage = stages.GetDatarepoStage(
            daft_lake_log=fake_datarepo._log, dtype=MyFakeDataclass, read_limit=limit
        )
        assert len(optimized_tree.nodes()) == 1
        assert [v for _, v in optimized_tree.nodes().items()][0]["stage"] == expected_optimized_read_stage


def test_query_filter(fake_datarepo: DataRepo) -> None:
    pred = FilterPredicate(left="id", comparator=">", right="5")
    q = fake_datarepo.query(MyFakeDataclass).filter(pred)
    expected_stages = [
        stages.GetDatarepoStage(daft_lake_log=fake_datarepo._log, dtype=MyFakeDataclass, read_limit=None),
        stages.FilterStage(predicate=pred),
    ]
    assert len(q._query_tree.nodes()) == 2
    assert [k for k in q._query_tree.nodes()][-1] == q._root
    assert [v["stage"] for _, v in q._query_tree.nodes().items()] == expected_stages


def test_query_apply(fake_datarepo: DataRepo) -> None:
    f = lambda x: 1
    q = fake_datarepo.query(MyFakeDataclass).apply(f, QueryColumn(name="foo"), somekwarg=QueryColumn(name="bar"))
    expected_stages = [
        stages.GetDatarepoStage(daft_lake_log=fake_datarepo._log, dtype=MyFakeDataclass, read_limit=None),
        stages.ApplyStage(f=f, args=(QueryColumn(name="foo"),), kwargs={"somekwarg": QueryColumn(name="bar")}),
    ]
    assert len(q._query_tree.nodes()) == 2
    assert [k for k in q._query_tree.nodes()][-1] == q._root
    assert [v["stage"] for _, v in q._query_tree.nodes().items()] == expected_stages
from __future__ import annotations

from superharness.engine import review_dao

T0 = "2026-01-01T00:00:00Z"


def test_record_and_stats(db_conn):
    review_dao.record(db_conn, owner="claude-code", task_type="feat",
                      duration_s=120.0, score=0.9, failed=False, now=T0)
    review_dao.record(db_conn, owner="claude-code", task_type="fix",
                      duration_s=60.0, score=0.7, failed=True, now=T0)

    s = review_dao.stats(db_conn, "claude-code")
    assert s.task_count == 2
    assert abs(s.avg_score - 0.8) < 0.01
    assert s.fail_rate == 0.5


def test_stats_empty(db_conn):
    s = review_dao.stats(db_conn, "nobody")
    assert s.task_count == 0
    assert s.avg_score == 0.0


def test_rank_owners(db_conn):
    for i in range(4):
        review_dao.record(db_conn, owner="a", task_type="", duration_s=50.0,
                          score=0.9, failed=False, now=T0)
    for i in range(4):
        review_dao.record(db_conn, owner="b", task_type="", duration_s=100.0,
                          score=0.8, failed=True, now=T0)

    ranked = review_dao.rank_owners(db_conn, min_task_count=3)
    assert len(ranked) == 2
    # 'a' has fail_rate=0, 'b' has fail_rate=1 -- 'a' should be first
    assert ranked[0].owner == "a"
    assert ranked[1].owner == "b"


def test_rank_owners_min_count_filter(db_conn):
    review_dao.record(db_conn, owner="rare", task_type="", duration_s=1.0,
                      score=1.0, failed=False, now=T0)
    ranked = review_dao.rank_owners(db_conn, min_task_count=3)
    assert all(r.owner != "rare" for r in ranked)

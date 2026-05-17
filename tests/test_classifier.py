"""Tests for standup/classifier.py."""

from standup.classifier import (
    COMMIT_TYPES,
    annotate_commits,
    classify_commit,
    filter_and_classify_commits,
    is_noise,
    summarize_by_type,
)


def test_classify_conventional_feat():
    assert classify_commit("feat(auth): add login flow") == "feat"


def test_classify_conventional_fix():
    assert classify_commit("fix: patch race condition") == "fix"


def test_classify_heuristic_docs():
    assert classify_commit("update README with setup notes") == "docs"


def test_classify_heuristic_ci():
    assert classify_commit("update GitHub Actions pipeline") == "ci"


def test_classify_merge_commit():
    assert classify_commit("Merge branch 'main' into feature") == "merge"


def test_classify_unknown_commit():
    assert classify_commit("misc cleanupish maybe") == "unknown"


def test_is_noise_detects_merge_remote():
    assert is_noise("merge remote-tracking branch origin/main") is True


def test_is_noise_detects_fixup():
    assert is_noise("fixup! feat: add parser") is True


def test_is_noise_false_for_real_work():
    assert is_noise("feat: ship standup cache") is False


def test_annotate_commits_adds_type_and_emoji():
    commits = [{"message": "fix: patch bug", "repo": "app"}]
    annotated = annotate_commits(commits)
    assert annotated[0]["type"] == "fix"
    assert annotated[0]["type_emoji"] == COMMIT_TYPES["fix"][0]


def test_filter_and_classify_commits_removes_noise():
    commits = [
        {"message": "fix: patch bug", "repo": "app"},
        {"message": "WIP sketch", "repo": "app"},
    ]
    filtered = filter_and_classify_commits(commits)
    assert len(filtered) == 1
    assert filtered[0]["type"] == "fix"


def test_summarize_by_type_counts_types():
    commits = annotate_commits(
        [
            {"message": "feat: add summary", "repo": "app"},
            {"message": "fix: patch summary", "repo": "app"},
            {"message": "feat: add history", "repo": "app"},
        ]
    )
    summary = summarize_by_type(commits)
    assert summary["feat"] == 2
    assert summary["fix"] == 1

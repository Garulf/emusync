import pytest

from emusync.decide import Action, Base, decide
from emusync.model import FileEntry, Manifest, Version

EMPTY = Manifest.empty()
A = Manifest.of([FileEntry("a.srm", "1" * 64, 1, 1.0)])
B = Manifest.of([FileEntry("a.srm", "2" * 64, 1, 2.0)])
C = Manifest.of([FileEntry("a.srm", "3" * 64, 1, 3.0)])


def head(number, manifest):
    return Version(number, "other", "2026-10-08T00:00:00+00:00", None, manifest)


@pytest.mark.parametrize(
    "local, head_version, expected",
    [
        (EMPTY, None, Action.NOTHING),
        (A, None, Action.PUSH),
        (EMPTY, head(1, A), Action.PULL),
        (A, head(1, A), Action.ADOPT),
        (B, head(1, A), Action.CONFLICT),
    ],
)
def test_first_sync(local, head_version, expected):
    assert decide(local, None, head_version) is expected


def test_neither_changed():
    assert decide(A, Base(1, A), head(1, A)) is Action.NOTHING


def test_only_local_changed_pushes():
    assert decide(B, Base(1, A), head(1, A)) is Action.PUSH


def test_only_remote_changed_pulls():
    assert decide(A, Base(1, A), head(2, B)) is Action.PULL


def test_both_changed_conflicts():
    assert decide(C, Base(1, A), head(2, B)) is Action.CONFLICT


def test_both_changed_to_identical_content_adopts():
    assert decide(B, Base(1, A), head(2, B)) is Action.ADOPT


def test_emptied_folder_is_never_pushed():
    assert decide(EMPTY, Base(1, A), head(1, A)) is Action.SKIP_EMPTY
    assert decide(EMPTY, Base(1, A), head(2, B)) is Action.SKIP_EMPTY


def test_empty_base_and_empty_local_with_new_remote_pulls():
    assert decide(EMPTY, Base(1, EMPTY), head(2, A)) is Action.PULL


def test_server_lost_slot_reseeds_from_local():
    assert decide(A, Base(5, A), None) is Action.PUSH
    assert decide(EMPTY, Base(5, EMPTY), None) is Action.NOTHING


def test_server_rolled_back_never_silently_reverts():
    assert decide(A, Base(5, A), head(3, B)) is Action.CONFLICT
    assert decide(A, Base(5, A), head(3, A)) is Action.ADOPT


X1 = FileEntry("x.srm", "4" * 64, 1, 1.0)
X2 = FileEntry("x.srm", "5" * 64, 1, 1.0)
Y1 = FileEntry("y.srm", "6" * 64, 1, 1.0)
Y2 = FileEntry("y.srm", "7" * 64, 1, 1.0)


def test_interrupted_first_pull_resumes_as_pull():
    assert decide(Manifest.of([X1]), None, head(1, Manifest.of([X1, Y1]))) is Action.PULL


def test_interrupted_pull_resumes_as_pull():
    base = Base(1, Manifest.of([X1, Y1]))
    half_applied = Manifest.of([X2, Y1])
    assert decide(half_applied, base, head(2, Manifest.of([X2, Y2]))) is Action.PULL


def test_interrupted_pull_with_deletion_resumes_as_pull():
    base = Base(1, Manifest.of([X1, Y1]))
    assert decide(Manifest.of([X2, Y1]), base, head(2, Manifest.of([X2]))) is Action.PULL


def test_own_edit_not_on_server_is_still_a_conflict():
    base = Base(1, Manifest.of([X1, Y1]))
    assert decide(Manifest.of([X1, Y2]), base, head(2, Manifest.of([X2, Y1]))) is Action.CONFLICT


def test_same_version_number_with_different_content_is_server_divergence():
    assert decide(C, Base(1, A), head(1, B)) is Action.CONFLICT
    assert decide(A, Base(1, A), head(1, B)) is Action.CONFLICT
    assert decide(B, Base(1, A), head(1, B)) is Action.ADOPT


def test_newer_empty_head_never_deletes_local_saves():
    assert decide(A, Base(3, A), head(4, EMPTY)) is Action.CONFLICT
    base = Base(3, Manifest.of([X1, Y1]))
    assert decide(Manifest.of([Y1]), base, head(4, EMPTY)) is Action.CONFLICT

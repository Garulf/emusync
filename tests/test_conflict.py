from emusync.client.api import Offline
from emusync.client.sync import MAX_CONFLICT_ROUNDS, Choice, Outcome

SLOT = "retroarch/saves"


class Scripted:
    def __init__(self, *choices):
        self.choices = list(choices)
        self.asked = []

    def choose(self, slot, local, server):
        self.asked.append((slot, server.number))
        return self.choices.pop(0)


def diverge(make_device, prompter):
    deck, pc = make_device("deck"), make_device("pc", prompter)
    deck.write("game.srm", b"base")
    deck.syncer.sync(SLOT, deck.root)
    pc.syncer.sync(SLOT, pc.root)
    deck.write("game.srm", b"deck progress")
    deck.syncer.sync(SLOT, deck.root)
    pc.write("game.srm", b"pc progress")
    return deck, pc


def test_keep_local_pushes_over_server(make_device):
    prompter = Scripted(Choice.LOCAL)
    deck, pc = diverge(make_device, prompter)
    assert pc.syncer.sync(SLOT, pc.root) is Outcome.KEPT_LOCAL
    assert prompter.asked == [(SLOT, 2)]
    assert deck.syncer.sync(SLOT, deck.root) is Outcome.PULLED
    assert deck.files() == {"game.srm": b"pc progress"}
    history = pc.syncer.api.history(SLOT)
    assert [v.number for v in history] == [3, 2, 1]


def test_keep_server_preserves_local_copy_in_history(make_device):
    deck, pc = diverge(make_device, Scripted(Choice.SERVER))
    assert pc.syncer.sync(SLOT, pc.root) is Outcome.KEPT_SERVER
    assert pc.files() == {"game.srm": b"deck progress"}
    history = pc.syncer.api.history(SLOT)
    assert [(v.number, v.label) for v in history][:2] == [(4, "restore-of:2"), (3, "conflict-lost")]
    assert pc.syncer.sync(SLOT, pc.root) is Outcome.IN_SYNC
    assert deck.syncer.sync(SLOT, deck.root) is Outcome.PULLED
    assert deck.files() == {"game.srm": b"deck progress"}


def test_lost_copy_can_be_restored(make_device):
    deck, pc = diverge(make_device, Scripted(Choice.SERVER))
    pc.syncer.sync(SLOT, pc.root)
    assert pc.syncer.restore(SLOT, pc.root, 3) is Outcome.PULLED
    assert pc.files() == {"game.srm": b"pc progress"}


def test_skip_leaves_everything_alone(make_device):
    deck, pc = diverge(make_device, Scripted(None))
    assert pc.syncer.sync(SLOT, pc.root) is Outcome.SKIPPED_CONFLICT
    assert pc.files() == {"game.srm": b"pc progress"}
    assert pc.syncer.api.head(SLOT).number == 2


def test_conflict_reprompts_when_server_moves_during_prompt(make_device):
    deck, pc = None, None

    class MovesServerFirst(Scripted):
        def choose(self, slot, local, server):
            if not self.asked:
                deck.write("game.srm", b"deck again")
                deck.syncer.sync(SLOT, deck.root)
            return super().choose(slot, local, server)

    prompter = MovesServerFirst(Choice.LOCAL, Choice.LOCAL)
    deck, pc = diverge(make_device, prompter)
    assert pc.syncer.sync(SLOT, pc.root) is Outcome.KEPT_LOCAL
    assert prompter.asked == [(SLOT, 2), (SLOT, 3)]
    assert pc.syncer.api.head(SLOT).number == 4


def test_offline_during_keep_server_changes_nothing_and_reprompts_next_time(make_device):
    prompter = Scripted(Choice.SERVER, Choice.SERVER)
    deck, pc = diverge(make_device, prompter)
    real = pc.syncer.api.keep_server

    def offline(*_args, **_kwargs):
        raise Offline("down")

    pc.syncer.api.keep_server = offline
    assert pc.syncer.sync(SLOT, pc.root) is Outcome.OFFLINE
    assert pc.state.base(SLOT).version == 1
    assert pc.syncer.api.head(SLOT).number == 2
    assert pc.files() == {"game.srm": b"pc progress"}

    pc.syncer.api.keep_server = real
    assert pc.syncer.sync(SLOT, pc.root) is Outcome.KEPT_SERVER
    assert prompter.asked == [(SLOT, 2), (SLOT, 2)]
    assert pc.files() == {"game.srm": b"deck progress"}


def test_server_moving_during_keep_server_then_skip_changes_nothing(make_device):
    deck, pc = None, None

    class MovesServerThenSkips(Scripted):
        def choose(self, slot, local, server):
            if not self.asked:
                deck.write("game.srm", b"deck again")
                deck.syncer.sync(SLOT, deck.root)
            return super().choose(slot, local, server)

    prompter = MovesServerThenSkips(Choice.SERVER, None)
    deck, pc = diverge(make_device, prompter)
    assert pc.syncer.sync(SLOT, pc.root) is Outcome.SKIPPED_CONFLICT
    assert prompter.asked == [(SLOT, 2), (SLOT, 3)]
    assert pc.state.base(SLOT).version == 1
    assert pc.files() == {"game.srm": b"pc progress"}
    pc.syncer.prompter = Scripted(None)
    assert pc.syncer.sync(SLOT, pc.root) is Outcome.SKIPPED_CONFLICT


def test_conflict_gives_up_after_max_rounds(make_device):
    deck, pc = None, None

    class ServerAlwaysMoves:
        def __init__(self):
            self.asked = 0

        def choose(self, slot, local, server):
            self.asked += 1
            deck.write("game.srm", f"deck {self.asked}".encode())
            deck.syncer.sync(SLOT, deck.root)
            return Choice.LOCAL

    prompter = ServerAlwaysMoves()
    deck, pc = diverge(make_device, prompter)
    assert pc.syncer.sync(SLOT, pc.root) is Outcome.SKIPPED_CONFLICT
    assert prompter.asked == MAX_CONFLICT_ROUNDS
    assert pc.state.base(SLOT).version == 1

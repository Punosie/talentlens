"""Team mode: connect with an invite link; sync through the team's server (no database
credentials on this computer). Uses an in-memory fake of the team server's API."""

from __future__ import annotations

import functools
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import talentlens.state as state_mod
from talentlens.connections import TeamBackend, check_team_server, redeem_invite

from .test_connections import person

SERVER = "https://team.example"
CODE = "A" * 24
TOKEN = "T" * 43


class FakeTeam:
    """The web app's /api/tl/* endpoints, in memory."""

    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.docs = sorted(docs, key=lambda d: d["_id"])
        self.revoked = False
        self.cvs: list[dict[str, Any]] = []
        self.redeemed = False

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/api/tl/redeem":
            body = json.loads(req.content)
            if body.get("code") != CODE or self.redeemed:
                return httpx.Response(
                    400, json={"error": "This invite link has expired or was already used."}
                )
            self.redeemed = True
            return httpx.Response(200, json={"token": TOKEN, "name": "Priya", "server": SERVER})
        if req.headers.get("authorization") != f"Bearer {TOKEN}" or self.revoked:
            return httpx.Response(401, json={"error": "Access removed"})
        if path == "/api/tl/people":
            limit = int(req.url.params.get("limit", 200))
            after = req.url.params.get("after")
            rows = [d for d in self.docs if after is None or d["_id"] > after]
            page = rows[:limit]
            items = [{**d, "migrated_at": d["migrated_at"].isoformat()} for d in page]
            return httpx.Response(
                200,
                json={
                    "items": items,
                    "count": None if after else len(self.docs),
                    "next": page[-1]["_id"] if len(page) == limit else None,
                },
            )
        if path == "/api/tl/cv":
            body = json.loads(req.content)
            self.cvs.append(body)
            return httpx.Response(
                200, json={"person_id": f"cv:{body['sha256'][:20].lower()}", "created": True}
            )
        if path == "/api/tl/me":
            return httpx.Response(200, json={"name": "Priya", "server": SERVER})
        return httpx.Response(404)


def _docs(n: int = 3) -> list[dict[str, Any]]:
    for d in (docs := [person(f"p-{i}", name=f"Person {i}") for i in range(n)]):
        d["owners"] = [{"account": "alice", "connected_on": None}]
    return docs


@pytest.fixture
def team(monkeypatch: pytest.MonkeyPatch) -> FakeTeam:
    fake = FakeTeam(_docs())
    transport = httpx.MockTransport(lambda req: fake.handler(req))  # late-bound: tests may swap it
    monkeypatch.setattr(
        state_mod, "redeem_invite", functools.partial(redeem_invite, transport=transport)
    )
    monkeypatch.setattr(
        state_mod, "TeamBackend", functools.partial(TeamBackend, transport=transport)
    )
    return fake


def wait(client: TestClient) -> None:
    assert client.app.state.tl.queue.wait_idle(120)


def join(
    client: TestClient,
    link: str = f"{SERVER}/join/{CODE}",
    origin: str | None = "http://testserver",
):
    headers = {"Origin": origin} if origin else {}
    return client.post("/api/connections/join", json={"invite": link}, headers=headers)


# --------------------------------------------------------------------------- pure checks


def test_team_server_must_be_https() -> None:
    assert check_team_server("https://team.example/x") == "https://team.example"
    assert check_team_server("http://127.0.0.1:3000") == "http://127.0.0.1:3000"
    for bad in (
        "http://team.example",
        "ftp://team.example",
        "https://user:pw@team.example",
        "nonsense",
    ):
        with pytest.raises(ValueError):
            check_team_server(bad)


def test_redeem_rejects_non_invite_links() -> None:
    with pytest.raises(ValueError, match="invite link"):
        redeem_invite("https://team.example/somewhere/else")


# --------------------------------------------------------------------------- end to end


def test_join_requires_a_click_from_talentlens_itself(client: TestClient, team: FakeTeam) -> None:
    assert join(client, origin=None).status_code == 403
    assert join(client, origin="https://evil.example").status_code == 403
    assert not team.redeemed


def test_join_syncs_through_the_team_server(client: TestClient, team: FakeTeam) -> None:
    r = join(client)
    assert r.status_code == 200 and r.json()["name"] == "Priya"
    wait(client)

    s = client.get("/api/settings").json()["connections"]
    assert s["mode"] == "team" and s["team"] == {"server": SERVER, "name": "Priya"}
    assert TOKEN not in json.dumps(client.get("/api/settings").json())  # token never echoed

    found = client.get("/api/search", params={"source": "linkedin"}).json()
    assert found["total"] == 3 and found["items"][0]["owners"] == ["alice"]

    # the 3 fixture resumes were shared through the server (no database credentials here)
    assert len(team.cvs) == 3 and all(c["sha256"] for c in team.cvs)
    assert "text" not in team.cvs[0]  # the resume text itself is not uploaded

    # the invite is single-use
    assert join(client).status_code == 400


def test_revoked_access_shows_a_clear_message(client: TestClient, team: FakeTeam) -> None:
    join(client)
    wait(client)
    team.revoked = True
    client.post("/api/connections/sync")
    wait(client)
    st = client.get("/api/connections/status").json()
    assert st["state"] == "error" and "access was removed" in st["error"]


def test_paging_through_many_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    import talentlens.connections as conn_mod

    monkeypatch.setattr(conn_mod, "PAGE_SIZE", 2)
    fake = FakeTeam(_docs(5))
    b = TeamBackend(SERVER, TOKEN, transport=httpx.MockTransport(fake.handler))
    assert b.count(None) == 5
    assert [d["_id"] for d in b.pages(None)] == [f"p-{i}" for i in range(5)]


def test_leave_disconnects(client: TestClient, team: FakeTeam) -> None:
    join(client)
    wait(client)
    assert (
        client.post("/api/connections/leave", headers={"Origin": "http://testserver"}).status_code
        == 200
    )
    assert client.get("/api/settings").json()["connections"]["mode"] == "off"


def test_sharing_off_on_server_is_not_an_error(
    client: TestClient, team: FakeTeam, monkeypatch
) -> None:
    """Before the team enables resume sharing, syncing connections still works without errors."""
    orig = team.handler

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/tl/cv":
            return httpx.Response(503, json={"error": "Saving resumes isn't switched on"})
        return orig(req)

    team.handler = handler  # type: ignore[method-assign]
    join(client)
    wait(client)
    st = client.get("/api/connections/status").json()
    assert st["state"] == "idle" and st["profiles"] == 3 and not st.get("error")

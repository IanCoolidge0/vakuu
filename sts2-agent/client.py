"""HTTP client for the STS2 mod API."""

import time
import requests


class GameClient:
    def __init__(self, base_url: str = "http://localhost:58232", timeout: float = 60.0):
        self.base_url = base_url
        self.timeout = timeout
        self.session = requests.Session()

    def _get(self, path: str) -> dict:
        resp = self.session.get(f"{self.base_url}{path}", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, data: dict) -> dict:
        resp = self.session.post(f"{self.base_url}{path}", json=data, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    # --- State endpoints ---

    def health(self) -> dict:
        return self._get("/health")

    def get_state(self) -> dict:
        return self._get("/game/state")

    def get_combat(self) -> dict:
        return self._get("/game/combat")

    def get_combat_piles(self) -> dict:
        return self._get("/game/combat/piles")

    def get_map(self) -> dict:
        return self._get("/game/map")

    def get_deck(self) -> dict:
        return self._get("/game/deck")

    # --- Combat actions (sync — waits for resolution) ---

    def play_card(self, card_index: int, target_index: int | None = None,
                  select_index: int | None = None) -> dict:
        data = {"type": "play_card", "card_index": card_index}
        if target_index is not None:
            data["target_index"] = target_index
        if select_index is not None:
            data["select_index"] = select_index
        return self._post("/game/action/combat", data)

    def end_turn(self) -> dict:
        return self._post("/game/action/combat", {"type": "end_turn"})

    def use_potion(self, potion_index: int, target_index: int | None = None) -> dict:
        data = {"type": "use_potion", "potion_index": potion_index}
        if target_index is not None:
            data["target_index"] = target_index
        return self._post("/game/action/combat", data)

    # --- Non-combat actions ---

    def choose_map_node(self, col: int, row: int) -> dict:
        return self._post("/game/action", {"type": "choose_map_node", "col": col, "row": row})

    def choose_event_option(self, index: int) -> dict:
        return self._post("/game/action", {"type": "choose_event_option", "card_index": index})

    def claim_reward(self, index: int) -> dict:
        return self._post("/game/action", {"type": "claim_reward", "card_index": index})

    def proceed(self) -> dict:
        return self._post("/game/action", {"type": "proceed"})

    def choose_card_reward(self, index: int) -> dict:
        return self._post("/game/action", {"type": "choose_card_reward", "card_index": index})

    def skip_card_reward(self) -> dict:
        return self._post("/game/action", {"type": "skip_card_reward"})

    def choose_rest_option(self, index: int, select_index: int | None = None) -> dict:
        data = {"type": "choose_rest_option", "card_index": index}
        if select_index is not None:
            data["select_index"] = select_index
        return self._post("/game/action", data)

    def shop_buy(self, index: int) -> dict:
        return self._post("/game/action", {"type": "shop_buy", "card_index": index})

    def shop_remove_card(self, select_index: int) -> dict:
        return self._post("/game/action", {"type": "shop_remove_card", "select_index": select_index})

    def shop_leave(self) -> dict:
        return self._post("/game/action", {"type": "shop_leave"})

    # --- Polling helpers ---

    def wait_for_screen(self, *expected_screens: str, max_retries: int = 10,
                        delay: float = 0.5) -> dict:
        """Poll /game/state until the screen matches one of the expected types."""
        for _ in range(max_retries):
            state = self.get_state()
            if state.get("screen") in expected_screens:
                return state
            time.sleep(delay)
        return self.get_state()  # return whatever we have

    def wait_for_not_screen(self, *screens_to_leave: str, max_retries: int = 10,
                            delay: float = 0.5) -> dict:
        """Poll /game/state until the screen is NOT one of the given types."""
        for _ in range(max_retries):
            state = self.get_state()
            if state.get("screen") not in screens_to_leave:
                return state
            time.sleep(delay)
        return self.get_state()

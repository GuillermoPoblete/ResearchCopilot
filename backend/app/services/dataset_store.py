from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock

import pandas as pd


@dataclass
class DatasetEntry:
    user_id: str
    project_id: str
    sheet_url: str
    context: dict
    dataframe: pd.DataFrame
    updated_at: datetime


class InMemoryDatasetStore:
    def __init__(self):
        self._entries: dict[str, DatasetEntry] = {}
        self._lock = Lock()

    @staticmethod
    def _key(user_id: str, project_id: str) -> str:
        return f"{user_id}:{project_id}"

    def set(
        self,
        *,
        user_id: str,
        project_id: str,
        sheet_url: str,
        context: dict,
        dataframe: pd.DataFrame,
    ) -> DatasetEntry:
        key = self._key(user_id, project_id)
        entry = DatasetEntry(
            user_id=user_id,
            project_id=project_id,
            sheet_url=sheet_url,
            context=context,
            dataframe=dataframe,
            updated_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._entries[key] = entry
        return entry

    def get(self, *, user_id: str, project_id: str) -> DatasetEntry | None:
        key = self._key(user_id, project_id)
        with self._lock:
            return self._entries.get(key)


dataset_store = InMemoryDatasetStore()

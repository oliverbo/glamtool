from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx


@dataclass(frozen=True)
class GhostPost:
    id: str
    title: str
    status: str
    published_at: Optional[str]
    url: Optional[str]
    feature_image: Optional[str]
    slug: Optional[str]
    html: Optional[str] = None


class GhostContentClient:
    """
    Client for Ghost Content API.
    Docs: https://ghost.org/docs/content-api/
    """

    def __init__(self, base_url: str, content_key: str, timeout_s: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.content_key = content_key
        self.timeout_s = timeout_s

    def _endpoint(self, path: str) -> str:
        # Content API base path is /ghost/api/content/
        return f"{self.base_url}/ghost/api/content/{path.lstrip('/')}"

    def list_posts(
        self,
        limit: int = 15,
        include: str = "authors,tags",
        fields: str = "id,title,status,published_at,url,feature_image,slug",
        filter_: Optional[str] = None,
        order: Optional[str] = None,
        page: int = 1,
    ) -> List[GhostPost]:
        params: Dict[str, Any] = {
            "key": self.content_key,
            "limit": min(max(limit, 1), 100),
            "page": page,
            "include": include,
            "fields": fields,
        }
        if filter_:
            params["filter"] = filter_
        if order:
            params["order"] = order

        url = self._endpoint("posts/")
        with httpx.Client(timeout=self.timeout_s) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            payload = r.json()

        posts = payload.get("posts", [])
        out: List[GhostPost] = []
        for p in posts:
            out.append(
                GhostPost(
                    id=p.get("id"),
                    title=p.get("title"),
                    status=p.get("status"),
                    published_at=p.get("published_at"),
                    url=p.get("url"),
                    feature_image=p.get("feature_image"),
                    slug=p.get("slug"),
                    html=p.get("html"),
                )
            )
        return out

    def paginate_posts(
        self,
        per_page: int = 100,
        include: str = "authors,tags",
        fields: str = "id,title,status,published_at,url,feature_image,slug",
        filter_: Optional[str] = None,
        order: Optional[str] = None,
        max_pages: int = 50,
    ) -> List[GhostPost]:
        all_posts: List[GhostPost] = []
        for page in range(1, max_pages + 1):
            batch = self.list_posts(
                limit=per_page,
                include=include,
                fields=fields,
                filter_=filter_,
                order=order,
                page=page,
            )
            if not batch:
                break
            all_posts.extend(batch)
            if len(batch) < per_page:
                break
        return all_posts

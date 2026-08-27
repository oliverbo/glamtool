from __future__ import annotations

import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx
import jwt


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

    @staticmethod
    def _post_from_payload(post: dict[str, Any]) -> GhostPost:
        return GhostPost(
            id=post.get("id"),
            title=post.get("title"),
            status=post.get("status"),
            published_at=post.get("published_at"),
            url=post.get("url"),
            feature_image=post.get("feature_image"),
            slug=post.get("slug"),
            html=post.get("html"),
        )

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
        return [self._post_from_payload(post) for post in posts]

    def get_post_by_slug(
        self,
        slug: str,
        *,
        fields: str = "id,title,status,published_at,url,feature_image,slug,html",
    ) -> GhostPost:
        url = self._endpoint(f"posts/slug/{quote(slug, safe='')}/")
        with httpx.Client(timeout=self.timeout_s) as client:
            response = client.get(
                url,
                params={"key": self.content_key, "fields": fields},
            )
            response.raise_for_status()
            payload = response.json()
        try:
            return self._post_from_payload(payload["posts"][0])
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"Ghost did not return a post for slug {slug!r}") from exc

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


class GhostAdminClient:
    """Authenticated client for creating and updating Ghost posts and their images."""

    def __init__(self, base_url: str, admin_key: str, timeout_s: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.admin_key = admin_key.strip()
        self.timeout_s = timeout_s
        self._key_id, self._secret = self._parse_key(self.admin_key)

    @staticmethod
    def _parse_key(admin_key: str) -> tuple[str, bytes]:
        try:
            key_id, secret = admin_key.split(":", 1)
            secret_bytes = bytes.fromhex(secret)
        except (ValueError, TypeError) as exc:
            raise ValueError("GHOST_ADMIN_KEY must use the '<id>:<hex-secret>' format") from exc
        if not key_id or not secret_bytes:
            raise ValueError("GHOST_ADMIN_KEY must use the '<id>:<hex-secret>' format")
        return key_id, secret_bytes

    def _endpoint(self, path: str) -> str:
        return f"{self.base_url}/ghost/api/admin/{path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        now = int(time.time())
        token = jwt.encode(
            {"iat": now, "exp": now + 5 * 60, "aud": "/admin/"},
            self._secret,
            algorithm="HS256",
            headers={"kid": self._key_id, "typ": "JWT"},
        )
        return {
            "Authorization": f"Ghost {token}",
            "Accept-Version": "v5.0",
        }

    def upload_image(self, path: Path) -> str:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as handle, httpx.Client(timeout=self.timeout_s) as client:
            response = client.post(
                self._endpoint("images/upload/"),
                headers=self._headers(),
                files={"file": (path.name, handle, content_type)},
                data={"purpose": "image", "ref": str(path)},
            )
            response.raise_for_status()
            payload = response.json()
        try:
            return payload["images"][0]["url"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"Ghost returned an invalid image upload response for {path}") from exc

    def create_draft(
        self,
        *,
        title: str,
        html: str,
        tags: Optional[list[str]] = None,
        authors: Optional[list[str]] = None,
        feature_image: Optional[str] = None,
        feature_image_alt: Optional[str] = None,
        feature_image_caption: Optional[str] = None,
    ) -> dict[str, Any]:
        post: dict[str, Any] = {"title": title, "html": html, "status": "draft"}
        if tags:
            post["tags"] = tags
        if authors:
            post["authors"] = authors
        if feature_image:
            post["feature_image"] = feature_image
        if feature_image_alt:
            post["feature_image_alt"] = feature_image_alt
        if feature_image_caption:
            post["feature_image_caption"] = feature_image_caption

        with httpx.Client(timeout=self.timeout_s) as client:
            response = client.post(
                self._endpoint("posts/"),
                headers=self._headers(),
                params={"source": "html"},
                json={"posts": [post]},
            )
            response.raise_for_status()
            payload = response.json()
        try:
            return payload["posts"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Ghost returned an invalid post creation response") from exc

    def get_post(self, post_id: str) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout_s) as client:
            response = client.get(
                self._endpoint(f"posts/{quote(post_id, safe='')}/"),
                headers=self._headers(),
                params={"formats": "html"},
            )
            response.raise_for_status()
            payload = response.json()
        try:
            return payload["posts"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"Ghost returned an invalid post response for {post_id!r}") from exc

    def update_post_html(self, post_id: str, *, html: str, updated_at: str) -> dict[str, Any]:
        if not updated_at:
            raise ValueError("Ghost post is missing updated_at; refusing an unsafe update")
        post = {"html": html, "updated_at": updated_at}
        with httpx.Client(timeout=self.timeout_s) as client:
            response = client.put(
                self._endpoint(f"posts/{quote(post_id, safe='')}/"),
                headers=self._headers(),
                params={"source": "html"},
                json={"posts": [post]},
            )
            response.raise_for_status()
            payload = response.json()
        try:
            return payload["posts"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"Ghost returned an invalid update response for {post_id!r}") from exc

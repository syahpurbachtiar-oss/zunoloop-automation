"""Minimal Buffer GraphQL client, using the public API."""
import json
from urllib.request import Request, urlopen


ENDPOINT = "https://api.buffer.com"

ORGANIZATIONS_QUERY = """
query GetOrganizations {
  account { organizations { id } }
}
"""

CHANNELS_QUERY = """
query GetChannels($organizationId: OrganizationId!) {
  channels(input: { organizationId: $organizationId }) { id service }
}
"""

POSTS_QUERY = """
query PostsForSlot($input: PostsInput!) {
  posts(first: 100, input: $input) {
    edges { node { id dueAt status channelId } }
    pageInfo { hasNextPage }
  }
}
"""

MUTATION = """
mutation CreateVideo($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id dueAt status } }
    ... on MutationError { message }
  }
}
"""


def _graphql(api_key, query, variables):
    payload = {"query": query, "variables": variables}
    request = Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key,
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        result = json.load(response)
    if result.get("errors"):
        raise RuntimeError("Buffer GraphQL error: " + str(result["errors"]))
    return result["data"]


def organization_for_channels(api_key, expected_channels):
    """Find the one Buffer organization containing the configured channels."""
    orgs = _graphql(api_key, ORGANIZATIONS_QUERY, {})["account"]["organizations"]
    matches = []
    for org in orgs:
        channels = _graphql(api_key, CHANNELS_QUERY,
                            {"organizationId": org["id"]})["channels"]
        by_id = {channel["id"]: channel["service"].lower() for channel in channels}
        if all(by_id.get(channel_id) == service
               for channel_id, service in expected_channels.items()):
            matches.append(org["id"])
    if len(matches) != 1:
        raise RuntimeError("Configured Instagram, TikTok and YouTube channels do not uniquely match one Buffer organization")
    return matches[0]


def slot_has_post(api_key, organization_id, channel_id, due_at):
    from datetime import datetime, timedelta, timezone
    target = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
    start = (target - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    end = (target + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    result = _graphql(api_key, POSTS_QUERY, {"input": {
        "organizationId": organization_id,
        "filter": {"channelIds": [channel_id], "dueAt": {"start": start, "end": end}},
    }})["posts"]
    if result["pageInfo"]["hasNextPage"]:
        raise RuntimeError("Buffer slot check exceeded one page; refusing possible duplicate")
    return any(
        datetime.fromisoformat(edge["node"]["dueAt"].replace("Z", "+00:00"))
        .astimezone(timezone.utc) == target.astimezone(timezone.utc)
        for edge in result["edges"] if edge["node"].get("dueAt")
    )


def create_video_post(api_key, channel_id, video_url, caption, due_at, metadata):
    if not video_url.startswith("https://"):
        raise ValueError("Video URL must be a public HTTPS URL")
    action = _graphql(api_key, MUTATION, {"input": {
            "text": caption,
            "channelId": channel_id,
            "schedulingType": "automatic",
            "mode": "customScheduled",
            "dueAt": due_at,
            "assets": [{"video": {"url": video_url}}],
            "metadata": metadata,
            "aiAssisted": True,
        }})["createPost"]
    if not action.get("post", {}).get("id"):
        raise RuntimeError("Buffer rejected post: " + str(action.get("message", action)))
    return action["post"]

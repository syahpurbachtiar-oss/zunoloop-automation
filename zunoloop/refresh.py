"""Upgrade future queued Agnes media without replacing sent posts."""
import argparse
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from .render import finish_video, PROFILE
from .buffer import _graphql, POSTS_QUERY, organization_for_channels
from .pipeline import publish

def refresh():
    root = Path('output')
    entries = json.loads((root/'manifest.json').read_text())
    for entry in entries:
        if datetime.fromisoformat(entry['dueAt'].replace('Z','+00:00')) <= datetime.now(timezone.utc)+timedelta(minutes=15):
            continue
        if entry.get('renderProfile') == PROFILE:
            continue
        source = root/'sources'/('raw-'+entry['file'])
        legacy = not source.exists()
        if legacy:
            source = root/entry['file']
        filename = Path(entry['file']).stem+'-neural.mp4'
        finish_video(source, entry['story'], entry['language'], root/filename, legacy=legacy)
        entry['file'] = filename
        entry['renderProfile'] = PROFILE
        (root/'manifest.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2))

EDIT = '''mutation EditVideo($input: EditPostInput!) {
  editPost(input: $input) {
    ... on PostActionSuccess { post { id dueAt status } }
    ... on MutationError { message }
  }
}'''

def replace_queued():
    key=os.environ['BUFFER_API_KEY']
    expected={os.environ['BUFFER_INSTAGRAM_CHANNEL_ID']:'instagram', os.environ['BUFFER_TIKTOK_CHANNEL_ID']:'tiktok', os.environ['BUFFER_YOUTUBE_CHANNEL_ID']:'youtube'}
    org=organization_for_channels(key,expected)
    entries=json.loads(Path('output/manifest.json').read_text())
    for entry in entries:
        if entry.get('renderProfile') != PROFILE:
            continue
        target=datetime.fromisoformat(entry['dueAt'].replace('Z','+00:00'))
        if target<=datetime.now(timezone.utc)+timedelta(minutes=15):
            raise RuntimeError('Queued upgrade is too close to publication')
        channels=[c for c,s in expected.items() if (s=='youtube') == (entry['language']=='en')]
        for ch in channels:
            result=_graphql(key, POSTS_QUERY, {'input':{'organizationId':org,'filter':{'channelIds':[ch],'dueAt':{'start':(target-timedelta(minutes=1)).isoformat(),'end':(target+timedelta(minutes=1)).isoformat()}}}})['posts']
            for edge in result['edges']:
                post=edge['node']
                if datetime.fromisoformat(post['dueAt'].replace('Z','+00:00')) != target:
                    continue
                if post['status'].lower() not in ('scheduled','pending','queued'):
                    raise RuntimeError('Refusing to modify non-queued post: '+str(post))
                url=os.environ['MEDIA_BASE_URL'].rstrip('/')+'/media/'+entry['file']
                action=_graphql(key,EDIT,{'input':{'id':post['id'],'assets':[{'video':{'url':url}}],'aiAssisted':True}})['editPost']
                if not action.get('post',{}).get('id'):
                    raise RuntimeError(str(action))
                print('Upgraded queued post: '+str(action['post']),flush=True)
    publish()  # Add missing slots with the new media; existing slots are deduplicated.

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--publish',action='store_true')
    args=parser.parse_args()
    replace_queued() if args.publish else refresh()

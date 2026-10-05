"""Operator-started stdio MCP, scoped to one user AND one person.

The local Host gains access to this person's confirmed accounts. No remote MCP endpoint.
"""
import argparse
import os
from sqlalchemy import select
from .database import Database, users
from .store import ScopedStore

def build_server(database_url,username,person_id):
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations
    db=Database(database_url)
    with db.read() as c:uid=c.execute(select(users.c.id).where(users.c.username==username)).scalar()
    if not uid:raise ValueError('Unknown account')
    store=ScopedStore(db,uid,[person_id]);store.person(person_id)
    server=FastMCP('Persona AI: one selected person')
    annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False)
    @server.tool(annotations=annotations)
    def get_person_profile()->dict:
        """Read user-provided profile; impressions and zodiac are not verified behavioral facts."""
        return {'source':'user_profile_unverified','profile':store.person(person_id)['profile']}
    @server.tool(annotations=annotations)
    def search_person_events(query:str='')->dict:
        """Return up to 8 confirmed user accounts, never simulations or another person's records."""
        if len(query)>200:raise ValueError('Query too long')
        rows=[x for x in store.list_events(person_id) if x['status']=='confirmed']
        words=query.lower().split()
        rows.sort(key=lambda x:(sum(w in x['text'].lower() for w in words),x['created']),reverse=True)
        selected=[];used=0
        for x in rows:
            item={k:x[k] for k in ('id','text','kind','occurred_at')}
            used+=len(x['text'])
            if used>6000:break
            selected.append(item)
            if len(selected)>=8:break
        return {'source':'user_report_unverified','events':selected}
    return server

def main():
    from dotenv import load_dotenv
    load_dotenv()
    p=argparse.ArgumentParser();p.add_argument('--username',required=True);p.add_argument('--person-id',required=True);a=p.parse_args()
    build_server(os.getenv('DATABASE_URL','sqlite:///memory/persona.sqlite3'),a.username,a.person_id).run(transport='stdio')
if __name__=='__main__':main()

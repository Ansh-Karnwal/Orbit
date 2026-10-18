"""Read-only Photon readiness check. Run from repo root:
PYTHONPATH=backend .venv/bin/python backend/scripts/check_photon.py
Never sends messages; prints only masked recipients and assigned Orbit lines.
"""
import asyncio
from photon_api import AsyncPhoton
from photon_api.rpc_generated import ListSharedLineAssignmentsInput
from app.core.config import get_settings
from app.adapters.settings import get_integration_settings
from app.adapters.photon import PhotonMessagingAdapter, _err
from app.adapters.base import mask_handle
async def main():
 s=get_settings(); p=get_integration_settings()
 c=AsyncPhoton(headers={'Authorization':f'Bearer {s.photon_api_key}'},timeout=15,max_attempts=1)
 try:
  page=await c.projects.platforms.imessage.assignments.list(ListSharedLineAssignmentsInput.model_validate({'path':{'id':p.photon_project_id}}))
  print('Photon authentication: OK')
  for a in page.assignments:
   if a.handle in (s.live_provider_a_handle,s.live_provider_b_handle): print('Provider:',mask_handle(a.handle),'Orbit line:',a.assignedPhoneNumber,'released:',isinstance(a.releasedAt,str))
  print('Assignment count:',len(page.assignments))
  adapter=PhotonMessagingAdapter()
  try:
   for h in sorted(adapter.allowed): print('Inbound route',mask_handle(h), 'ready' if await adapter._discover_space(h) else 'not found')
  finally: await adapter.client.close()
 except Exception as e: print('Photon check failed:',_err(e))
 finally: await c.close()
asyncio.run(main())

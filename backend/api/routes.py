from fastapi import APIRouter


router = APIRouter()

@router.post('/run')
async def run_agent():
    return {"result": "Agent is running"}

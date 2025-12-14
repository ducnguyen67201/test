from app.db import AsyncSessionLocal
from app.models.lab import Lab, LabStatus
from sqlalchemy import select
import asyncio

async def show_labs_status():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Lab).where(Lab.status.in_([LabStatus.ENDING, LabStatus.FINISHED]))
        )
        labs = result.scalars().all()
        for lab in labs:
            print(f"Lab {lab.id}: status={lab.status}, owner={lab.owner_id}")

if __name__ == "__main__":
    asyncio.run(show_labs_status())

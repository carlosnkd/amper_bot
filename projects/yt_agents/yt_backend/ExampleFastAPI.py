from fastapi import FastAPI, Body 

app = FastAPI(
            title="Agentic AI API",
            docs_url="/docs",
)

#Path parameters
#Get can not have a body part
@app.get("/home/{path_param}")
async def first_api(path_param):
    return {"message": f"Hello, World! {path_param}"}

#Create pieces of data
#Body creates a space in which I can pass data and not just a field in Swagger UI
@app.post("/home/create")
async def create_item(item = Body()):
    return {"message": "Item created successfully", "item": item}

#Update pieces of data
@app.put("/home/update/{item_id}")
async def update_item(item_id: int, item = Body()):
    return {"message": f"Item {item_id} updated successfully", "item": item}

@app.delete("/home/delete/{item_id}")
async def delete_item(item_id: int):
    return {"message": f"Item {item_id} deleted successfully"}

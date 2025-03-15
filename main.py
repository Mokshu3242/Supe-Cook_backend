import sqlite3
import os
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from typing import List
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# List of origins to allow
origins = [
    "http://localhost:5173",  # React development server
    "http://localhost",
]

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Path to your SQLite database file
DB_PATH = "./recipe-dataset-main/13k-recipes.db"  # Update if needed

# Function to get all recipes from the database
def get_all_recipes():
    try:
        if not os.path.exists(DB_PATH):
            return JSONResponse(status_code=404, content={"message": "Database file not found."})

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM recipes")
            recipes = cursor.fetchall()

        structured_recipes = [
            {
                "id": recipe[0],
                "name": recipe[1],
                "ingredients": eval(recipe[2]),
                "instructions": recipe[3],
            }
            for recipe in recipes
        ]

        return structured_recipes
    except sqlite3.OperationalError as e:
        return JSONResponse(status_code=500, content={"message": f"Database error: {str(e)}"})

# Function to search recipes by a query string
def search_recipes(query: str):
    recipes = get_all_recipes()
    if isinstance(recipes, JSONResponse):
        return recipes

    query_words = set(query.lower().split())
    filtered_recipes = [
        recipe for recipe in recipes if all(word in recipe["name"].lower() for word in query_words)
    ]
    return filtered_recipes

# Function to search recipes by ingredients
def search_recipes_by_ingredients(ingredients: List[str]):
    recipes = get_all_recipes()
    if isinstance(recipes, JSONResponse):
        return recipes

    ingredient_words = [ingredient.lower() for ingredient in ingredients]
    filtered_recipes = [
        recipe for recipe in recipes 
        if all(any(ingredient.lower() in item.lower() for item in recipe["ingredients"]) for ingredient in ingredient_words)
    ]
    return filtered_recipes

# Pydantic model for ingredient search
class IngredientsRequest(BaseModel):
    ingredients: List[str]

@app.get("/search")
async def search(query: str):
    if not query:
        return JSONResponse(status_code=400, content={"message": "Query parameter is required."})
    return {"results": search_recipes(query)}

@app.post("/search_by_ingredients")
async def search_by_ingredients(request: IngredientsRequest):
    if not request.ingredients:
        return JSONResponse(status_code=400, content={"message": "Ingredients list is required."})
    return {"results": search_recipes_by_ingredients(request.ingredients)}

@app.get("/all_recipes")
async def get_all():
    recipes = get_all_recipes()
    return recipes if isinstance(recipes, JSONResponse) else {"results": recipes}

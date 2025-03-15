from fastapi import FastAPI, HTTPException, Depends, status
from pymongo import MongoClient
from pydantic import BaseModel
from typing import List, Optional
from bson import ObjectId
import os
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import requests  # for image URL validation

# Load environment variables
load_dotenv()
MONGODB_URI = os.getenv("MONGODB_URI")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Connect to MongoDB Atlas
client = MongoClient(MONGODB_URI)
db = client["supercook"]
users_collection = db["users"]
favorites_collection = db["favorite_recipes"]

app = FastAPI()

# Allow frontend to access API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

# Helper functions
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def serialize_document(doc):
    doc["id"] = str(doc["_id"])
    del doc["_id"]
    return doc

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_email: str = payload.get("sub")
        if not user_email:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        user = users_collection.find_one({"email": user_email})
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        return serialize_document(user)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

def check_image_url(image_url: str) -> bool:
    """Check if the image URL is accessible."""
    try:
        response = requests.get(image_url)
        if response.status_code == 200 and 'image' in response.headers.get('Content-Type', ''):
            return True
        return False
    except requests.exceptions.RequestException:
        return False

class User(BaseModel):
    name: str
    email: str
    password: Optional[str] = None  # Make password optional for updates
    profile_image: str = None  # Optional image URL

class Token(BaseModel):
    access_token: str
    token_type: str

class FavoriteRecipe(BaseModel):
    image: str
    name: str
    ingredients: List[str]
    instructions: str

@app.post("/users/", response_model=dict)
def create_user(user: User):
    if users_collection.find_one({"email": user.email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    user_dict = user.dict()
    user_dict["password"] = get_password_hash(user.password)
    # Store user in MongoDB, including the profile_image URL if provided
    users_collection.insert_one(user_dict)
    return {"message": "User created successfully"}

@app.put("/users/", response_model=dict)
def update_user(user: User, current_user: dict = Depends(get_current_user)):
    # Ensure the user is the one who is logged in
    if current_user["email"] != user.email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only update your own profile")
    
    # Validate the profile image URL if provided
    if user.profile_image and not check_image_url(user.profile_image):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provided image URL is not accessible")
    
    # Prepare the user data for update, exclude unset fields (not passed in the request)
    update_data = user.dict(exclude_unset=True)  # Only include fields passed in the request
    
    # If password is not provided in the request, keep the existing password
    if "password" in update_data:
        update_data["password"] = get_password_hash(update_data["password"])  # Hash the new password
    
    # Update user data in the database
    result = users_collection.update_one(
        {"email": current_user["email"]},
        {"$set": update_data}
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found or no changes made")

    return {"message": "Profile updated successfully"}

@app.post("/token", response_model=Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = users_collection.find_one({"email": form_data.username})
    if not user or not verify_password(form_data.password, user["password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    access_token = create_access_token(data={"sub": user["email"]})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/profile", response_model=dict)
def get_user_profile(current_user: dict = Depends(get_current_user)):
    return current_user

@app.delete("/users/delete_account/", response_model=dict)
def delete_user_account(current_user: dict = Depends(get_current_user)):
    # Delete the user's favorite recipes first (optional, depending on your requirements)
    favorites_collection.delete_many({"email": current_user["email"]})
    
    # Delete the user from the users collection
    result = users_collection.delete_one({"email": current_user["email"]})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    return {"message": "User account and associated data deleted successfully"}

# Favorite Recipes Endpoints
@app.post("/recipes/", response_model=dict)
def add_favorite_recipe(recipe: FavoriteRecipe, current_user: dict = Depends(get_current_user)):
    # Add the user's email to the recipe data
    recipe_dict = recipe.dict()
    recipe_dict["email"] = current_user["email"]
    
    # Check if the recipe already exists for the user
    existing_recipe = favorites_collection.find_one({"email": current_user["email"], "name": recipe_dict["name"]})
    if existing_recipe:
        raise HTTPException(status_code=400, detail="Recipe with this title already exists for the user")
    
    # Insert the new recipe into the database
    favorites_collection.insert_one(recipe_dict)
    return {"message": "Recipe added successfully"}

@app.get("/get_recipes/", response_model=List[dict])
def get_user_recipes(title: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    # Build the query based on the user's email and optional title
    query = {"email": current_user["email"]}
    if title:
        query["name"] = title  # Assuming "name" is the field for the recipe title
    
    # Retrieve and serialize the recipes
    recipes = [serialize_document(recipe) for recipe in favorites_collection.find(query)]
    return recipes

@app.delete("/delete_recipes/", response_model=dict)
def delete_favorite_recipe(title: str, current_user: dict = Depends(get_current_user)):
    # Ensure the recipe belongs to the current user before deleting
    recipe = favorites_collection.find_one({"email": current_user["email"], "name": title})
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found or you don't have permission to delete it")
    
    # Delete the recipe
    favorites_collection.delete_one({"email": current_user["email"], "name": title})
    return {"message": "Recipe deleted successfully"}

# Run with: uvicorn Api:app --reload

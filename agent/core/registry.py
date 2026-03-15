import os
import json
from langchain_core.tools import StructuredTool

def load_skills():
    """Dynamically load all skills from the skills directory based on their manifests."""
    skills_dir = os.path.join(os.path.dirname(__file__), "skills")
    tools = []
    
    if not os.path.exists(skills_dir):
        return tools
        
    for skill_name in os.listdir(skills_dir):
        skill_path = os.path.join(skills_dir, skill_name)
        if not os.path.isdir(skill_path):
            continue
            
        manifest_path = os.path.join(skill_path, "manifest.json")
        execute_path = os.path.join(skill_path, "execute.py")
        
        if not os.path.exists(manifest_path) or not os.path.exists(execute_path):
            continue
            
        # Load the manifest
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
            
        # Dynamically import the execute module
        import importlib.util
        spec = importlib.util.spec_from_file_location(f"skill_{skill_name}", execute_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        if not hasattr(module, "execute"):
            print(f"WARNING: Skill {skill_name} is missing an 'execute' function.")
            continue
            
        # Create Langchain StructuredTool
        tool = StructuredTool.from_function(
            func=module.execute,
            name=manifest["name"],
            description=manifest["description"],
        )
        tools.append(tool)
        
    return tools

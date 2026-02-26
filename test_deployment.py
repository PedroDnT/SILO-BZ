#!/usr/bin/env python3
"""
Test script to verify APIs are ready for deployment
"""

import sys
import importlib.util

def test_imports():
    """Test that all required modules can be imported"""
    print("Testing imports...")
    
    required_modules = [
        'fastapi',
        'uvicorn',
        'pydantic',
        'slowapi',
        'httpx',
        'pandas',
        'numpy'
    ]
    
    failed = []
    for module in required_modules:
        try:
            __import__(module)
            print(f"  ✓ {module}")
        except ImportError:
            print(f"  ✗ {module} - NOT FOUND")
            failed.append(module)
    
    if failed:
        print(f"\n❌ Missing modules: {', '.join(failed)}")
        print("Install with: pip install -r requirements-vercel.txt")
        return False
    
    print("✅ All imports successful\n")
    return True

def test_api_structure():
    """Test that API files exist and have correct structure"""
    print("Testing API structure...")
    
    apis = [
        'src/cvm_api/main.py',
        'src/bacen_api/main.py',
        'src/b3_calc_api/main.py'
    ]
    
    for api_path in apis:
        try:
            # Check file exists
            with open(api_path, 'r') as f:
                content = f.read()
                
            # Check for FastAPI app
            if 'app = FastAPI' not in content:
                print(f"  ✗ {api_path} - Missing FastAPI app")
                return False
            
            # Check for health endpoint
            if '/health' not in content:
                print(f"  ⚠ {api_path} - No health endpoint (optional)")
            
            print(f"  ✓ {api_path}")
            
        except FileNotFoundError:
            print(f"  ✗ {api_path} - NOT FOUND")
            return False
    
    print("✅ API structure valid\n")
    return True

def test_vercel_config():
    """Test that Vercel configuration is valid"""
    print("Testing Vercel configuration...")
    
    import json
    
    try:
        with open('vercel.json', 'r') as f:
            config = json.load(f)
        
        # Check required fields
        if 'builds' not in config:
            print("  ✗ Missing 'builds' in vercel.json")
            return False
        
        if 'routes' not in config:
            print("  ✗ Missing 'routes' in vercel.json")
            return False
        
        # Check builds
        builds = config['builds']
        if len(builds) < 3:
            print(f"  ⚠ Only {len(builds)} builds configured (expected 3)")
        
        print(f"  ✓ {len(builds)} builds configured")
        print(f"  ✓ {len(config['routes'])} routes configured")
        
        print("✅ Vercel configuration valid\n")
        return True
        
    except FileNotFoundError:
        print("  ✗ vercel.json not found")
        return False
    except json.JSONDecodeError:
        print("  ✗ vercel.json is not valid JSON")
        return False

def test_requirements():
    """Test that requirements file exists"""
    print("Testing requirements...")
    
    try:
        with open('requirements-vercel.txt', 'r') as f:
            requirements = f.read()
        
        required_packages = ['fastapi', 'uvicorn', 'pydantic']
        missing = []
        
        for package in required_packages:
            if package not in requirements.lower():
                missing.append(package)
        
        if missing:
            print(f"  ✗ Missing packages: {', '.join(missing)}")
            return False
        
        print("  ✓ requirements-vercel.txt valid")
        print("✅ Requirements file valid\n")
        return True
        
    except FileNotFoundError:
        print("  ✗ requirements-vercel.txt not found")
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("Brazilian Financial Data APIs - Deployment Test")
    print("=" * 60)
    print()
    
    tests = [
        test_requirements,
        test_imports,
        test_api_structure,
        test_vercel_config
    ]
    
    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"❌ Test failed with error: {e}\n")
            results.append(False)
    
    print("=" * 60)
    if all(results):
        print("✅ All tests passed! Ready for deployment.")
        print()
        print("Next steps:")
        print("  1. Run: vercel")
        print("  2. Or: ./deploy.sh")
        print("=" * 60)
        return 0
    else:
        print("❌ Some tests failed. Fix issues before deploying.")
        print("=" * 60)
        return 1

if __name__ == '__main__':
    sys.exit(main())

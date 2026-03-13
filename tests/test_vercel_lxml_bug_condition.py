"""
Bug Condition Exploration Test for Vercel lxml Deployment Failure

**Validates: Requirements 1.1, 1.2, 1.3**

This test explores the bug condition where Vercel deployment fails due to missing
INSTALLER metadata file for lxml 6.0.2. This is a FAULT CONDITION test that is
EXPECTED TO FAIL on unfixed code.

CRITICAL: This test MUST FAIL on unfixed code - failure confirms the bug exists.
DO NOT attempt to fix the test or code when it fails.

The test encodes the expected behavior - it will validate the fix when it passes
after lxml is pinned to 5.3.0.
"""

import pytest
import subprocess
import os
import sys
from pathlib import Path
from hypothesis import given, strategies as st, settings, Phase
from hypothesis import HealthCheck


# Property 1: Fault Condition - Vercel Deployment Fails with lxml 6.0.2 Metadata Error
# **Validates: Requirements 1.1, 1.2, 1.3**


def get_requirements_files():
    """Get all requirements files that need lxml pinning"""
    project_root = Path(__file__).parent.parent
    return [
        project_root / "requirements.txt",
        project_root / "requirements-vercel.txt",
        project_root / "src" / "cvm_api" / "requirements.txt",
        project_root / "src" / "bacen_api" / "requirements.txt",
        project_root / "src" / "b3_calc_api" / "requirements.txt",
    ]


def check_lxml_pinned_in_requirements():
    """
    Check if lxml is explicitly pinned in requirements files.
    Returns (is_pinned, files_without_pin)
    """
    files_without_pin = []
    
    for req_file in get_requirements_files():
        if not req_file.exists():
            continue
            
        content = req_file.read_text()
        lines = content.split('\n')
        
        # Check if lxml is explicitly pinned (lxml==5.3.0 or similar)
        has_lxml_pin = any(
            line.strip().startswith('lxml==') 
            for line in lines 
            if not line.strip().startswith('#')
        )
        
        if not has_lxml_pin:
            files_without_pin.append(str(req_file))
    
    return len(files_without_pin) == 0, files_without_pin


def simulate_vercel_build_with_lxml_602():
    """
    Simulate Vercel build process that would install lxml 6.0.2.
    
    This simulates the bug condition:
    - Create a temporary venv
    - Install pandas (which pulls in lxml as transitive dependency)
    - Check if lxml 6.0.2 gets installed
    - Check if INSTALLER file is missing from lxml-6.0.2.dist-info
    
    Returns: (lxml_version, installer_exists, error_message)
    """
    import tempfile
    import shutil
    
    # Create temporary directory for test venv
    temp_dir = tempfile.mkdtemp(prefix="vercel_lxml_test_")
    
    try:
        venv_path = Path(temp_dir) / "test_venv"
        
        # Create virtual environment
        result = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_path)],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            return None, None, f"Failed to create venv: {result.stderr}"
        
        # Get pip path
        if os.name == 'nt':
            pip_path = venv_path / "Scripts" / "pip"
        else:
            pip_path = venv_path / "bin" / "pip"
        
        # Install pandas without lxml pin (simulates current buggy configuration)
        # This should pull in lxml as a transitive dependency
        result = subprocess.run(
            [str(pip_path), "install", "pandas==2.1.3", "--no-cache-dir"],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode != 0:
            return None, None, f"Failed to install pandas: {result.stderr}"
        
        # Check which version of lxml was installed
        result = subprocess.run(
            [str(pip_path), "show", "lxml"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            return None, None, "lxml not installed"
        
        # Parse lxml version from pip show output
        lxml_version = None
        for line in result.stdout.split('\n'):
            if line.startswith('Version:'):
                lxml_version = line.split(':', 1)[1].strip()
                break
        
        if not lxml_version:
            return None, None, "Could not determine lxml version"
        
        # Check if INSTALLER file exists in dist-info
        if os.name == 'nt':
            site_packages = venv_path / "Lib" / "site-packages"
        else:
            # Find the correct Python version directory
            lib_path = venv_path / "lib"
            python_dirs = list(lib_path.glob("python*"))
            if not python_dirs:
                return lxml_version, None, "Could not find site-packages"
            site_packages = python_dirs[0] / "site-packages"
        
        dist_info_dir = site_packages / f"lxml-{lxml_version}.dist-info"
        installer_file = dist_info_dir / "INSTALLER"
        
        installer_exists = installer_file.exists()
        
        return lxml_version, installer_exists, None
        
    finally:
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.slow
def test_bug_condition_lxml_metadata_missing():
    """
    Bug Condition Exploration Test: Vercel Deployment Fails with lxml 6.0.2 Metadata Error
    
    **Validates: Requirements 1.1, 1.2, 1.3**
    
    This test verifies the bug condition exists:
    - Current requirements files do NOT explicitly pin lxml version
    - When pandas is installed, it may pull in lxml 6.0.2 as transitive dependency
    - lxml 6.0.2 has missing INSTALLER file in dist-info directory
    - This causes Vercel deployment to fail with ENOENT error
    
    EXPECTED OUTCOME: This test FAILS on unfixed code, confirming the bug exists.
    When the fix is applied (lxml==5.3.0 pinned), this test will PASS.
    """
    
    # Check 1: Verify lxml is NOT explicitly pinned in requirements files
    # This is the bug condition - without explicit pin, we get problematic version
    is_pinned, files_without_pin = check_lxml_pinned_in_requirements()
    
    # On unfixed code, lxml should NOT be pinned
    # On fixed code, lxml SHOULD be pinned to 5.3.0
    assert is_pinned, (
        f"Bug condition detected: lxml is not explicitly pinned in requirements files. "
        f"Files without lxml pin: {files_without_pin}. "
        f"This allows installation of lxml 6.0.2 which has incomplete metadata, "
        f"causing Vercel deployment to fail with ENOENT error for INSTALLER file."
    )
    
    # Check 2: Simulate what happens during Vercel build
    # Install pandas (like Vercel does) and check if lxml has complete metadata
    print("\n=== Simulating Vercel Build Process ===")
    print("Installing pandas without explicit lxml pin...")
    
    lxml_version, installer_exists, error = simulate_vercel_build_with_lxml_602()
    
    if error:
        pytest.fail(f"Build simulation failed: {error}")
    
    print(f"Installed lxml version: {lxml_version}")
    print(f"INSTALLER file exists: {installer_exists}")
    
    # Check 3: Verify the bug condition
    # If lxml 6.0.2 is installed, INSTALLER file should be missing (bug condition)
    # If lxml 5.3.0 is installed (after fix), INSTALLER file should exist
    
    if lxml_version == "6.0.2":
        # This is the bug condition - lxml 6.0.2 with missing INSTALLER
        assert installer_exists, (
            f"BUG CONFIRMED: lxml {lxml_version} is missing INSTALLER file in dist-info. "
            f"This causes Vercel deployment to fail with: "
            f"'ENOENT: no such file or directory, lstat "
            f"'/vercel/path0/.vercel/python/.venv/lib/python3.12/site-packages/"
            f"lxml-6.0.2.dist-info/INSTALLER'. "
            f"Expected behavior: lxml should be pinned to 5.3.0 with complete metadata."
        )
    elif lxml_version == "5.3.0":
        # This is the fixed state - lxml 5.3.0 should have complete metadata
        assert installer_exists, (
            f"lxml {lxml_version} is installed but INSTALLER file is missing. "
            f"Even the pinned version has incomplete metadata."
        )
    else:
        # Some other version was installed
        print(f"WARNING: Unexpected lxml version {lxml_version} installed")
        assert installer_exists, (
            f"lxml {lxml_version} is missing INSTALLER file. "
            f"Expected lxml 5.3.0 with complete metadata."
        )


@given(st.just("pandas==2.1.3"))
@settings(
    max_examples=1,
    phases=[Phase.generate, Phase.target],
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_property_vercel_deployment_bug_condition(pandas_version):
    """
    Property-Based Test: Vercel Deployment Bug Condition
    
    **Validates: Requirements 1.1, 1.2, 1.3**
    
    Property: For any Vercel deployment with current requirements configuration
    (no explicit lxml pin), the deployment SHALL fail with ENOENT error for
    lxml-6.0.2.dist-info/INSTALLER during package validation phase.
    
    This property test is scoped to the concrete failing case:
    - Vercel deployment with pandas 2.1.3 (from requirements-vercel.txt)
    - No explicit lxml version pin
    - Python 3.12 environment
    
    EXPECTED OUTCOME: Test FAILS on unfixed code (bug condition exists)
    After fix (lxml==5.3.0 pinned): Test PASSES (bug condition resolved)
    """
    
    # Verify the bug condition: lxml is not pinned
    is_pinned, files_without_pin = check_lxml_pinned_in_requirements()
    
    # The expected behavior is that lxml SHOULD be pinned
    # On unfixed code, this assertion will FAIL (confirming bug exists)
    # On fixed code, this assertion will PASS (confirming fix works)
    assert is_pinned, (
        f"FAULT CONDITION DETECTED: lxml is not explicitly pinned in requirements files. "
        f"Files missing lxml pin: {files_without_pin}. "
        f"\n\nThis configuration causes Vercel deployment to fail with: "
        f"\n  'ENOENT: no such file or directory, lstat "
        f"\n   /vercel/path0/.vercel/python/.venv/lib/python3.12/site-packages/"
        f"\n   lxml-6.0.2.dist-info/INSTALLER'"
        f"\n\nBug Condition Function:"
        f"\n  isBugCondition(deployment) = "
        f"\n    deployment.pythonVersion == '3.12'"
        f"\n    AND 'lxml' IN deployment.installedPackages"
        f"\n    AND deployment.installedPackages['lxml'].version == '6.0.2'"
        f"\n    AND NOT fileExists(lxml-6.0.2.dist-info/INSTALLER)"
        f"\n    AND deployment.buildPhase == 'package_validation'"
        f"\n\nExpected Fix: Pin lxml==5.3.0 in all requirements files to ensure "
        f"complete metadata and successful Vercel deployment."
    )


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "-s"])

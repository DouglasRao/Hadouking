import unittest
import shutil
import os
from pathlib import Path
from core.project_manager import ProjectManager

class TestProjectManager(unittest.TestCase):
    def setUp(self):
        self.test_base_dir = "TestProjects"
        if os.path.exists(self.test_base_dir):
            shutil.rmtree(self.test_base_dir)
            
    def tearDown(self):
        if os.path.exists(self.test_base_dir):
            shutil.rmtree(self.test_base_dir)

    def test_create_first_project(self):
        pm = ProjectManager(base_dir=self.test_base_dir)
        project_dir = pm.create_new_project()
        
        self.assertTrue(os.path.exists(project_dir))
        self.assertTrue(project_dir.endswith("Project_01"))
        self.assertTrue(os.path.exists(os.path.join(self.test_base_dir, "Project_01")))

    def test_increment_project_number(self):
        pm = ProjectManager(base_dir=self.test_base_dir)
        
        # Create Project_01
        dir1 = pm.create_new_project()
        self.assertTrue(dir1.endswith("Project_01"))
        
        # Create Project_02
        dir2 = pm.create_new_project()
        self.assertTrue(dir2.endswith("Project_02"))
        
        # Create Project_03
        dir3 = pm.create_new_project()
        self.assertTrue(dir3.endswith("Project_03"))

    def test_existing_directories(self):
        # Manually create Project_05
        os.makedirs(os.path.join(self.test_base_dir, "Project_05"))
        
        pm = ProjectManager(base_dir=self.test_base_dir)
        next_dir = pm.create_new_project()
        
        # Should skip to Project_06
        self.assertTrue(next_dir.endswith("Project_06"))

if __name__ == '__main__':
    unittest.main()

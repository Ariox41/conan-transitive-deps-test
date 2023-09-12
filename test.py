import os
import subprocess
import shutil
from typing import List
from typing_extensions import Self
import textwrap

build_folder = os.path.join(os.path.dirname(__file__), "build")
conan_cache_folder = os.path.join(build_folder, "conan2")


class Requirement:
    def __init__(self, package: "Package", version: str, transitive_headers: bool | None, transitive_libs: bool | None,):
        self.package = package
        self.version = version
        self.name = package.name
        assert type(transitive_headers) == type(
            True) or type(transitive_headers) == type(None)
        assert type(transitive_libs) == type(
            True) or type(transitive_libs) == type(None)
        self.transitive_headers = transitive_headers
        self.transitive_libs = transitive_libs


class TestRequirement:
    def __init__(self, package: "Package", version: str):
        self.package = package
        self.version = version
        self.name = package.name


class Package:
    def __init__(self, name: str, version: str):
        self.name = name
        self.version = version
        self.requirements: List[Requirement] = []
        self.test_requirements: List[TestRequirement] = []

    def requires(self, dep: Self, version: str, transitive_headers=None, transitive_libs=None) -> Self:
        self.requirements.append(
            Requirement(
                package=dep,
                version=version,
                transitive_headers=transitive_headers,
                transitive_libs=transitive_libs,
            )
        )
        return self

    def test_requires(self, dep: Self, version: str) -> Self:
        self.test_requirements.append(TestRequirement(dep, version))
        return self

    @property
    def conanfile_folder(self) -> str:
        return os.path.join(build_folder, self.name)

    def generate(self) -> None:
        pass

    def create(self) -> None:
        pass

    def create_graph(self) -> None:
        pass


class PyreqPackage(Package):
    def generate(self) -> None:
        os.mkdir(self.conanfile_folder)
        with open(os.path.join(self.conanfile_folder, "conanfile.py"), "w") as f:
            f.write(
                textwrap.dedent(
                    f"""
                from conan.tools.env import VirtualBuildEnv
                from conan.tools.cmake import cmake_layout, CMake, CMakeToolchain
                from conan import ConanFile
                class MyBase:
                    package_type="library"
                    implements = ["auto_shared_fpic", "auto_header_only"]
                    settings = "os", "compiler", "build_type", "arch"
                    options = {{"shared": [True, False], "fPIC": [True, False]}}
                    default_options = {{"shared": True, "fPIC": True}}
                    generators = ["CMakeDeps"]
                    
                    def layout(self):
                        cmake_layout(self)
                        
                    def package_info(self):
                        self.cpp_info.libs = [self.name]
                        
                    def generate(self):
                        VirtualBuildEnv(self).generate()
                        CMakeToolchain(self).generate()
                        
                    def build(self):
                        cmake = CMake(self)
                        cmake.configure()
                        cmake.build()
                        cmake.test()
                        
                    def package(self):
                        cmake = CMake(self)
                        cmake.configure()
                        cmake.install()

                class PyReq(ConanFile):
                    name = "{self.name}"
                    version = "0.1.0"
                    package_type = "python-require"
            """
                )
            )

    def create(self):
        subprocess.run(["conan", "create", "."],
                       cwd=self.conanfile_folder).check_returncode()


def br_indent(indent):
    return "\n" + " " * 4 * indent


class LibraryPackage(Package):
    def generate(self) -> None:
        os.mkdir(self.conanfile_folder)
        self._generate_conanfile()
        self._generate_cmakefile()
        self._generate_hpp()
        self._generate_cpp()
        self._generate_test_cpp()

    def create(self):
        subprocess.run(["conan", "build", "."],
                       cwd=self.conanfile_folder).check_returncode()
        subprocess.run(["conan", "export-pkg", "."],
                       cwd=self.conanfile_folder).check_returncode()

    def create_graph(self):
        with open(os.path.join(self.conanfile_folder, "graph.html"), "w") as f:
            subprocess.run(["conan", "graph", "info", ".", "-f", "html",],
                           cwd=self.conanfile_folder, stdout=f,).check_returncode()

    def _generate_conanfile(self) -> None:
        def transitive_headers(r):
            return (f"transitive_headers={r.transitive_headers}," if not r.transitive_headers is None else "")

        def transitive_libs(r):
            return (f"transitive_libs={r.transitive_libs}," if not r.transitive_libs is None else "")

        content = textwrap.dedent(
            f"""
            from conan import ConanFile
            
            class CMakeLibraryRecipe(ConanFile):
                name = "{self.name}"
                version = "{self.version}"
                python_requires = "pyreq/0.1.0"
                python_requires_extend = "pyreq.MyBase"
                
                def requirements(self):
                    {br_indent(5).join(f'self.requires("{r.name}/{r.version}", {transitive_headers(r)} {transitive_libs(r)})' 
                                       for r in self.requirements)}
                    pass
                def build_requirements(self):
                    {br_indent(5).join(f'self.test_requires("{r.name}/{r.version}")' for r in self.test_requirements)}
                    pass
            """
        )
        with open(os.path.join(self.conanfile_folder, "conanfile.py"), "w") as f:
            f.write(content)

    def _generate_cmakefile(self):
        content = textwrap.dedent(
            f"""
            cmake_minimum_required(VERSION 3.15)
            project({self.name})
            {br_indent(3).join(f"find_package({r.name} REQUIRED)"
                               for r in self.requirements + self.test_requirements)}

            add_library(${{PROJECT_NAME}} {self.name}.cpp {self.name}.hpp)
            set_target_properties(${{PROJECT_NAME}} PROPERTIES CXX_VISIBILITY_PRESET hidden)
            include(GenerateExportHeader) 
            generate_export_header(${{PROJECT_NAME}} EXPORT_MACRO_NAME {self.name}_export)
            target_include_directories(${{PROJECT_NAME}} PUBLIC "${{PROJECT_BINARY_DIR}}")
            set_target_properties(${{PROJECT_NAME}} PROPERTIES PUBLIC_HEADER {self.name}.hpp)
            install(TARGETS ${{PROJECT_NAME}})
            install(FILES "${{PROJECT_BINARY_DIR}}/${{PROJECT_NAME}}_export.h" TYPE INCLUDE)
            target_link_libraries(${{PROJECT_NAME}} PUBLIC 
                {br_indent(4).join(f"{r.package.name}::{r.package.name}" for r in self.requirements)}
            )
            
            enable_testing()
            add_executable(${{PROJECT_NAME}}_test ${{PROJECT_NAME}}_test.cpp)
            target_link_libraries(${{PROJECT_NAME}}_test PRIVATE ${{PROJECT_NAME}}
                {br_indent(4).join(f'{r.name}::{r.name}'for r in self.test_requirements)}
            )
            add_test(NAME ${{PROJECT_NAME}}_test COMMAND ${{PROJECT_NAME}}_test)
            """
        )
        with open(os.path.join(self.conanfile_folder, "CMakeLists.txt"), "w") as f:
            f.write(content)

    def _generate_hpp(self):
        content = textwrap.dedent(
            f"""
            #pragma once
            {br_indent(3).join(f"#include <{r.package.name}.hpp>"
                               for r in self.requirements if r.transitive_headers)}
            #include <{self.name}_export.h>
            #include <string>
            namespace {self.name}{{
                inline std::string test_headers(){{
                    return std::string("{self.name}")
                        {br_indent(6).join(f'+ " " + {r.package.name}::test_headers()'
                                           for r in self.requirements if r.transitive_headers)}; 
                }}
                std::string {self.name}_export test_link();
            }}
            """
        )
        with open(os.path.join(self.conanfile_folder, f"{self.name}.hpp"), "w") as f:
            f.write(content)

    def _generate_cpp(self):
        content = textwrap.dedent(
            f"""
            #include "{self.name}.hpp"
            {br_indent(3).join(f"#include <{r.package.name}.hpp>" for r in self.requirements if not r.transitive_headers)}
            namespace {self.name}{{
                std::string {self.name}_export test_link(){{
                    return std::string("{self.name}")
                        {br_indent(6).join(f'+ " " + {r.package.name}::test_link()' for r in self.requirements)};
                }}
            }}
            """
        )
        with open(os.path.join(self.conanfile_folder, f"{self.name}.cpp"), "w") as f:
            f.write(content)

    def _generate_test_cpp(self):

        content = textwrap.dedent(
            f"""
            #include "{self.name}.hpp"
            {br_indent(3).join(f"#include <{r.name}.hpp>" for r in self.test_requirements)}
            int main(){{
                {self.name}::test_headers();
                {self.name}::test_link();
                {br_indent(4).join(f'{r.name}::test_headers(); {r.name}::test_link();' for r in self.test_requirements)}
                return 0;
            }}
            """
        )
        with open(os.path.join(self.conanfile_folder, f"{self.name}_test.cpp"), "w") as f:
            f.write(content)


class TestContext:
    def __init__(self):
        self.packages: List[Package] = [PyreqPackage("pyreq", "0.1.0")]
        pass

    def library(self, name: str ,version: str) -> Package:
        package = LibraryPackage(name, version)
        self.packages.append(package)
        return package

    def generate(self):
        for p in self.packages:
            p.generate()

    def create_packages(self):
        for p in self.packages:
            p.create()

    def create_graph(self):
        for p in self.packages:
            p.create_graph()


def create_context() -> TestContext:
    ctx = TestContext()
    
    #req_versions = '0.1.0' # === error ===
    #req_versions = '[^0.1.0]' # === lib_c error ===
    req_versions = '[>=0.1.0]' # === lib_c error ===

    util = ctx.library("util", '0.1.0')

    lib_a = ctx.library("lib_a", '0.1.0') \
        .requires(util, req_versions)
        
    # works in any cases    
    lib_b = ctx.library("lib_b", '0.1.0') \
        .test_requires(util, req_versions) \
        .test_requires(lib_a, req_versions) 

    # error in case of version range
    lib_c = ctx.library("lib_c", '0.1.0') \
        .test_requires(lib_a, req_versions) \
        .test_requires(util, req_versions)

    return ctx


def main():
    os.environ["CONAN_HOME"] = conan_cache_folder
    shutil.rmtree(build_folder, ignore_errors=True)
    os.mkdir(build_folder)
    subprocess.run(["conan", "profile", "detect", "-f"],
                   cwd=build_folder).check_returncode()
    subprocess.run(["conan", "remote", "disable", "conancenter"],
                   cwd=build_folder).check_returncode()

    ctx = create_context()
    ctx.generate()
    ctx.create_packages()
    ctx.create_graph()


if __name__ == "__main__":
    main()

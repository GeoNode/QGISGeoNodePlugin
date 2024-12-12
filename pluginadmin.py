import configparser
import datetime as dt
import os
import re
import shlex
import shutil
import subprocess
import sys
import typing
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx
import toml
import typer

LOCAL_ROOT_DIR = Path(__file__).parent.resolve()
SRC_NAME = "qgis_geonode"
PACKAGE_NAME = SRC_NAME.replace("_", "")
app = typer.Typer()


@dataclass
class GithubRelease:
    pre_release: bool
    tag_name: str
    url: str
    published_at: dt.datetime


@app.callback()
def main(context: typer.Context, verbose: bool = False, qgis_profile: str = "default"):
    """Perform various development-oriented tasks for this plugin"""
    context.obj = {
        "verbose": verbose,
        "qgis_profile": qgis_profile,
    }


@app.command()
def install(context: typer.Context):
    """Deploy plugin to QGIS' plugins dir"""
    _log("Uninstalling...", context=context)
    uninstall(context)
    _log("Building...", context=context)
    built_dir = build(context, clean=True)
    base_target_dir = _get_qgis_root_dir(context) / "python/plugins" / SRC_NAME
    _log(f"Copying built plugin to {base_target_dir}...", context=context)
    shutil.copytree(built_dir, base_target_dir)
    _log(f"Installed {str(built_dir)!r} into {str(base_target_dir)!r}", context=context)


@app.command()
def uninstall(context: typer.Context):
    """Remove plugin from QGIS' plugins directory"""
    base_target_dir = _get_qgis_root_dir(context) / "python/plugins" / SRC_NAME
    shutil.rmtree(str(base_target_dir), ignore_errors=True)
    _log(f"Removed {str(base_target_dir)!r}", context=context)


@app.command()
def generate_zip(
    context: typer.Context, output_dir: typing.Optional[Path] = LOCAL_ROOT_DIR / "dist"
):
    build_dir = build(context)
    metadata = _get_metadata()
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f'{SRC_NAME}.{metadata["version"]}.zip'
    with zipfile.ZipFile(zip_path, "w") as fh:
        _add_to_zip(build_dir, fh, arc_path_base=build_dir.parent)
    typer.echo(f"zip generated at {str(zip_path)!r}")
    return zip_path


@app.command()
def build(
    context: typer.Context,
    output_dir: typing.Optional[Path] = LOCAL_ROOT_DIR / "build" / SRC_NAME,
    clean: bool = True,
) -> Path:
    if clean:
        shutil.rmtree(str(output_dir), ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    copy_source_files(output_dir)
    icon_path = copy_icon(context, output_dir)
    if icon_path is None:
        _log("Could not copy icon", context=context)
    licese_path = copy_license(context, output_dir)
    if licese_path is None:
        _log("Could not copy LICENSE file", context=context)
    compile_resources(context, output_dir)
    generate_metadata(context, output_dir)
    return output_dir

@app.command()
def copy_license(context: typer.Context,
    output_dir: typing.Optional[Path] = LOCAL_ROOT_DIR / "build/temp",
) -> Path:
    license_path = LOCAL_ROOT_DIR / "LICENSE"
    if license_path.is_file():
        target_path = output_dir / license_path.name
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(license_path, target_path)
        result = target_path
    else:
        result = None
    return result

@app.command()
def copy_icon(
    context: typer.Context,
    output_dir: typing.Optional[Path] = LOCAL_ROOT_DIR / "build/temp",
) -> Path:
    metadata = _get_metadata()
    icon_path = LOCAL_ROOT_DIR / "resources" / metadata["icon"]
    if icon_path.is_file():
        target_path = output_dir / icon_path.name
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(icon_path, target_path)
        result = target_path
    else:
        result = None
    return result


@app.command()
def copy_source_files(
    output_dir: typing.Optional[Path] = LOCAL_ROOT_DIR / "build/temp",
):
    output_dir.mkdir(parents=True, exist_ok=True)
    for child in (LOCAL_ROOT_DIR / "src" / SRC_NAME).iterdir():
        if child.name != "__pycache__":
            target_path = output_dir / child.name
            handler = shutil.copytree if child.is_dir() else shutil.copy
            handler(str(child.resolve()), str(target_path))


@app.command()
def compile_resources(
    context: typer.Context,
    output_dir: typing.Optional[Path] = LOCAL_ROOT_DIR / "build/temp",
):
    resources_path = LOCAL_ROOT_DIR / "resources" / "resources.qrc"
    target_path = output_dir / "resources.py"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _log(f"compile_resources target_path: {target_path}", context=context)
    subprocess.run(shlex.split(f"pyrcc5 -o {target_path.as_posix()} {resources_path.as_posix()}"))


@app.command()
def generate_metadata(
    context: typer.Context,
    output_dir: typing.Optional[Path] = LOCAL_ROOT_DIR / "build/temp",
):
    metadata = _get_metadata()
    target_path = output_dir / "metadata.txt"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _log(f"generate_metadata target_path: {target_path}", context=context)
    config = configparser.ConfigParser()
    # do not modify case of parameters, as per
    # https://docs.python.org/3/library/configparser.html#customizing-parser-behaviour
    config.optionxform = lambda option: option
    config["general"] = metadata
    with target_path.open(mode="w") as fh:
        config.write(fh)


@app.command()
def install_qgis_into_venv(
    context: typer.Context,
    pyqt5_dir: Path = os.getenv(
        "PYQT5_DIR_PATH", "/usr/lib/python3/dist-packages/PyQt5"
    ),
    sip_dir: Path = os.getenv("SIP_DIR_PATH", "/usr/lib/python3/dist-packages"),
    qgis_dir: Path = os.getenv(
        "QGIS_PYTHON_DIR_PATH", "/usr/lib/python3/dist-packages/qgis"
    ),
):
    venv_dir = _get_virtualenv_site_packages_dir()
    _log(f"venv_dir: {venv_dir}")
    _log(f"pyqt5_dir: {pyqt5_dir}")
    _log(f"sip_dir: {sip_dir}")
    _log(f"qgis_dir: {qgis_dir}")
    suitable, relevant_paths = _check_suitable_system(pyqt5_dir, sip_dir, qgis_dir)
    if suitable:
        target_pyqt5_dir_path = venv_dir / "PyQt5"
        print(f"Symlinking {relevant_paths['pyqt5']} to {target_pyqt5_dir_path}...")
        target_pyqt5_dir_path.symlink_to(
            relevant_paths["pyqt5"], target_is_directory=True
        )
        for sip_file in relevant_paths["sip"]:
            target = venv_dir / sip_file.name
            print(f"Symlinking {sip_file} to {target}...")
            target.symlink_to(sip_file)
        target_qgis_dir_path = venv_dir / "qgis"
        print(f"Symlinking {relevant_paths['qgis']} to {target_qgis_dir_path}...")
        target_qgis_dir_path.symlink_to(
            relevant_paths["qgis"], target_is_directory=True
        )
        final_message = "Done!"
    else:
        final_message = f"Could not find all relevant paths: {relevant_paths}"
    return final_message


@app.command()
def generate_plugin_repo_xml(
    context: typer.Context,
):
    repo_base_dir = LOCAL_ROOT_DIR / "docs" / "repo"
    repo_base_dir.mkdir(parents=True, exist_ok=True)
    metadata = _get_metadata()
    fragment_template = """
            <pyqgis_plugin name="{name}" version="{version}">
                <description><![CDATA[{description}]]></description>
                <about><![CDATA[{about}]]></about>
                <version>{version}</version>
                <qgis_minimum_version>{qgis_minimum_version}</qgis_minimum_version>
                <homepage><![CDATA[{homepage}]]></homepage>
                <file_name>{filename}</file_name>
                <icon>{icon}</icon>
                <author_name><![CDATA[{author}]]></author_name>
                <download_url>{download_url}</download_url>
                <update_date>{update_date}</update_date>
                <experimental>{experimental}</experimental>
                <deprecated>{deprecated}</deprecated>
                <tracker><![CDATA[{tracker}]]></tracker>
                <repository><![CDATA[{repository}]]></repository>
                <tags><![CDATA[{tags}]]></tags>
                <server>False</server>
            </pyqgis_plugin>
    """.strip()
    contents = "<?xml version = '1.0' encoding = 'UTF-8'?>\n<plugins>"
    all_releases = _get_existing_releases(context=context)
    for release in [r for r in _get_latest_releases(all_releases) if r is not None]:
        tag_name = release.tag_name
        _log(f"Processing release {tag_name}...", context=context)
        fragment = fragment_template.format(
            name=metadata.get("name"),
            version=tag_name.replace("v", ""),
            description=metadata.get("description"),
            about=metadata.get("about"),
            qgis_minimum_version=metadata.get("qgisMinimumVersion"),
            homepage=metadata.get("homepage"),
            filename=release.url.rpartition("/")[-1],
            icon=metadata.get("icon", ""),
            author=metadata.get("author"),
            download_url=release.url,
            update_date=release.published_at,
            experimental=release.pre_release,
            deprecated=metadata.get("deprecated"),
            tracker=metadata.get("tracker"),
            repository=metadata.get("repository"),
            tags=metadata.get("tags"),
        )
        contents = "\n".join((contents, fragment))
    contents = "\n".join((contents, "</plugins>"))
    repo_index = repo_base_dir / "plugins.xml"
    repo_index.write_text(contents, encoding="utf-8")
    _log(f"Plugin repo XML file saved at {repo_index}", context=context)


def _check_suitable_system(
    pyqt5_dir: Path, sip_dir: Path, qgis_dir: Path
) -> typing.Tuple[bool, typing.Dict]:
    pyqt5_found = pyqt5_dir.is_dir()
    try:
        sip_files = _find_sip_files(sip_dir)
    except IndexError:
        sip_files = []
    sip_found = len(sip_files) > 0
    qgis_found = qgis_dir.is_dir()
    suitable = pyqt5_found and sip_found and qgis_found
    return (
        suitable,
        {
            "pyqt5": pyqt5_dir,
            "sip": sip_files,
            "qgis": qgis_dir,
        },
    )


def _find_sip_files(sip_dir) -> typing.List[Path]:
    sip_so_file = list(sip_dir.glob("sip.*.so"))[0]
    sipconfig_files = list(sip_dir.glob("sipconfig*.py"))
    return sipconfig_files + [sip_so_file]


def _get_virtualenv_site_packages_dir() -> Path:
    venv_lib_root = Path(sys.executable).parents[1] / "lib"
    for item in [i for i in venv_lib_root.iterdir() if i.is_dir()]:
        if item.name.startswith("python"):
            python_lib_path = item
            break
    else:
        raise RuntimeError("Could not find site_packages_dir")
    site_packages_dir = python_lib_path / "site-packages"
    if site_packages_dir.is_dir():
        result = site_packages_dir
    else:
        raise RuntimeError(f"{site_packages_dir} does not exist")
    return result

def _get_author_names(authors):
    return [author.split("<")[0].strip() for author in authors]

def _get_author_emails(authors):
    return [author.split("<")[1].strip(">") for author in authors]

@lru_cache()
def _get_metadata() -> typing.Dict:
    conf = _parse_pyproject()
    poetry_conf = conf["tool"]["poetry"]
    
    metadata = conf["tool"]["qgis-plugin"]["metadata"].copy()
    metadata.update(
        {
            "author": ", ".join(_get_author_names(poetry_conf["authors"])),
            "email": ", ".join(_get_author_emails(poetry_conf["authors"])),
            "description": poetry_conf["description"],
            "version": poetry_conf["version"],
            "tags": ", ".join(metadata.get("tags", [])),
            "changelog": _parse_changelog(),
        }
    )
    return metadata


def _parse_pyproject():
    pyproject_path = LOCAL_ROOT_DIR / "pyproject.toml"
    with pyproject_path.open("r") as fh:
        return toml.load(fh)


def _parse_changelog() -> str:
    contents = _read_file("CHANGELOG.md")
    usable_fragment = contents.rpartition(f"## [Unreleased]")[-1].partition(
        "[unreleased]"
    )[0]
    release_parts = usable_fragment.split("\n## ")
    result = []
    current_change_type = "unreleased"
    for release_fragment in release_parts:
        lines: typing.List[str] = [li for li in release_fragment.splitlines()]
        for line in lines:
            if line.startswith("["):
                release, release_date = line.partition(" - ")[::2]
                release = release.strip("[]")
                result.append(f"\n{release} ({release_date})")
            elif line.startswith("### "):
                current_change_type = line.strip("### ").strip().lower()
            elif line.startswith("-"):
                message = line.strip("- ")
                result.append(f"- ({current_change_type}) {message}")
            else:
                pass
    return "\n".join(result)


def _read_file(relative_path: str):
    path = LOCAL_ROOT_DIR / relative_path
    with path.open() as fh:
        return fh.read()


def _add_to_zip(directory: Path, zip_handler: zipfile.ZipFile, arc_path_base: Path):
    for item in directory.iterdir():
        if item.is_file():
            zip_handler.write(item, arcname=str(item.relative_to(arc_path_base)))
        else:
            _add_to_zip(item, zip_handler, arc_path_base)


def _log(msg, *args, context: typing.Optional[typer.Context] = None, **kwargs):
    if context is not None:
        context_user_data = context.obj or {}
        verbose = context_user_data.get("verbose", True)
    else:
        verbose = True
    if verbose:
        typer.echo(msg, *args, **kwargs)


def _get_qgis_root_dir(context: typing.Optional[typer.Context] = None) -> Path:
    return (
        Path.home() / f".local/share/QGIS/QGIS3/profiles/{context.obj['qgis_profile']}"
    )


def _get_existing_releases(
    context: typing.Optional = None,
) -> typing.List[GithubRelease]:
    """Query the github API and retrieve existing releases"""
    # TODO: add support for pagination
    base_url = "https://api.github.com/repos/GeoNode/QGISGeoNodePlugin/releases"
    response = httpx.get(base_url, follow_redirects=True)
    result = []
    if response.status_code == 200:
        payload = response.json()
        for release in payload:
            for asset in release["assets"]:
                if asset.get("content_type") == "application/zip":
                    zip_download_url = asset.get("browser_download_url")
                    break
            else:
                zip_download_url = None
            _log(f"zip_download_url: {zip_download_url}", context=context)
            if zip_download_url is not None:
                result.append(
                    GithubRelease(
                        pre_release=release.get("prerelease", True),
                        tag_name=release.get("tag_name"),
                        url=zip_download_url,
                        published_at=dt.datetime.strptime(
                            release["published_at"], "%Y-%m-%dT%H:%M:%SZ"
                        ),
                    )
                )
    return result


def _get_latest_releases(
    current_releases: typing.List[GithubRelease],
) -> typing.Tuple[typing.Optional[GithubRelease], typing.Optional[GithubRelease]]:
    latest_experimental = None
    latest_stable = None
    for release in current_releases:
        if release.pre_release:
            if latest_experimental is not None:
                if release.published_at > latest_experimental.published_at:
                    latest_experimental = release
            else:
                latest_experimental = release
        else:
            if latest_stable is not None:
                if release.published_at > latest_stable.published_at:
                    latest_stable = release
            else:
                latest_stable = release
    return latest_stable, latest_experimental


if __name__ == "__main__":
    app()

import configparser
import re
import shlex
import shutil
import subprocess
import typing
import zipfile
from functools import lru_cache
from pathlib import Path

import toml
import typer

LOCAL_ROOT_DIR = Path(__file__).parent.resolve()
SRC_NAME = 'qgis_geonode'
PACKAGE_NAME = SRC_NAME.replace('_', '')
app = typer.Typer()


@app.callback()
def main(context: typer.Context, verbose: bool = False):
    """Perform various development-oriented tasks for this plugin"""
    context.obj = {
        "verbose": verbose
    }


@app.command()
def install(context: typer.Context):
    """Deploy plugin to QGIS' plugins dir"""
    _log("Uninstalling...", context=context)
    uninstall(context)
    _log("Building...", context=context)
    built_dir = build(context, clean=True)
    base_target_dir = _get_qgis_root_dir(context) / 'python/plugins' / SRC_NAME
    _log(f"Copying built plugin to {base_target_dir}...", context=context)
    shutil.copytree(built_dir, base_target_dir)
    _log(f'Installed {str(built_dir)!r} into {str(base_target_dir)!r}', context=context)


@app.command()
def uninstall(context: typer.Context):
    """Remove plugin from QGIS' plugins directory"""
    base_target_dir = _get_qgis_root_dir(context) / 'python/plugins' / SRC_NAME
    shutil.rmtree(str(base_target_dir), ignore_errors=True)
    _log(f'Removed {str(base_target_dir)!r}', context=context)


@app.command()
def generate_zip(
        context: typer.Context,
        output_dir: typing.Optional[Path] = LOCAL_ROOT_DIR / 'dist'
):
    build_dir = build(context)
    metadata = _get_metadata()
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f'{SRC_NAME}-v{metadata["version"]}.zip'
    with zipfile.ZipFile(zip_path, 'w') as fh:
        _add_to_zip(build_dir, fh, arc_path_base=build_dir.parent)
    typer.echo(f'zip generated at {str(zip_path)!r}')
    return zip_path


@app.command()
def build(
        context: typer.Context,
        output_dir: typing.Optional[Path] = LOCAL_ROOT_DIR / 'build' / SRC_NAME,
        clean: bool = True
) -> Path:
    if clean:
        shutil.rmtree(str(output_dir), ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    copy_source_files(output_dir)
    icon_path = copy_icon(context, output_dir)
    if icon_path is None:
        _log("Could not copy icon", context=context)
    compile_resources(context, output_dir)
    generate_metadata(context, output_dir)
    return output_dir


@app.command()
def copy_icon(
        context: typer.Context,
        output_dir: typing.Optional[Path] = LOCAL_ROOT_DIR / 'build/temp'
) -> Path:
    metadata = _get_metadata()
    icon_path = LOCAL_ROOT_DIR / 'resources' / metadata['icon']
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
        output_dir: typing.Optional[Path] = LOCAL_ROOT_DIR / 'build/temp'
):
    output_dir.mkdir(parents=True, exist_ok=True)
    for child in (LOCAL_ROOT_DIR / 'src' / SRC_NAME).iterdir():
        target_path = output_dir / child.name
        handler = shutil.copytree if child.is_dir() else shutil.copy
        handler(str(child.resolve()), str(target_path))


@app.command()
def compile_resources(
        context: typer.Context,
        output_dir: typing.Optional[Path] = LOCAL_ROOT_DIR / 'build/temp'
):
    resources_path = LOCAL_ROOT_DIR / 'resources' / 'resources.qrc'
    target_path = output_dir / PACKAGE_NAME / 'resources.py'
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _log(f'compile_resources target_path: {target_path}', context=context)
    subprocess.run(shlex.split(f'pyrcc5 -o {target_path} {resources_path}'))


@app.command()
def generate_metadata(
        context: typer.Context,
        output_dir: typing.Optional[Path] = LOCAL_ROOT_DIR / 'build/temp',
):
    metadata = _get_metadata()
    target_path = output_dir / 'metadata.txt'
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _log(f'generate_metadata target_path: {target_path}', context=context)
    config = configparser.ConfigParser()
    # do not modify case of parameters, as per
    # https://docs.python.org/3/library/configparser.html#customizing-parser-behaviour
    config.optionxform = lambda option: option
    config['general'] = metadata
    with target_path.open(mode='w') as fh:
        config.write(fh)


@lru_cache()
def _get_metadata() -> typing.Dict:
    conf = _parse_pyproject()
    poetry_conf = conf['tool']['poetry']
    raw_author_list = poetry_conf['authors'][0].split('<')
    author = raw_author_list[0].strip()
    email = raw_author_list[-1].replace('>', '')
    metadata = conf['tool']['qgis-plugin']['metadata'].copy()
    metadata.update({
        'author': author,
        'email': email,
        'description': poetry_conf['description'],
        'version': poetry_conf['version'],
        'tags': ', '.join(metadata.get('tags', [])),
        'changelog': _parse_changelog(
            _read_file('CHANGELOG.md'),
            poetry_conf["version"]
        ),
    })
    return metadata


def _parse_pyproject():
    pyproject_path = LOCAL_ROOT_DIR / 'pyproject.toml'
    with pyproject_path.open('r') as fh:
        return toml.load(fh)


def _parse_changelog(changelog: str, version: str) -> str:
    usable_fragment = changelog.partition(f'[{version}]')[-1].partition('[unreleased]')[0]
    if usable_fragment != "":
        no_square_brackets = re.sub(r'(\[(\d+.\d+.\d+)\])', '\g<2>', usable_fragment)
        result = f'{version} {no_square_brackets}'.replace('# ', '').replace('#', '')
    else:
        result = ""
    return result


def _read_file(relative_path: str):
    path = LOCAL_ROOT_DIR / relative_path
    with path.open() as fh:
        return fh.read()


def _add_to_zip(
        directory: Path,
        zip_handler: zipfile.ZipFile,
        arc_path_base: Path
):
    for item in directory.iterdir():
        if item.is_file():
            zip_handler.write(
                item,
                arcname=str(item.relative_to(arc_path_base))
            )
        else:
            _add_to_zip(item, zip_handler, arc_path_base)


def _log(
        msg,
        *args,
        context: typing.Optional[typer.Context] = None,
        **kwargs
):
    if context is not None:
        context_user_data = context.obj or {}
        verbose = context_user_data.get('verbose', True)
    else:
        verbose = True
    if verbose:
        typer.echo(msg, *args, **kwargs)


def _get_qgis_root_dir(context: typing.Optional[typer.Context] = None) -> Path:
    conf = _parse_pyproject()
    try:
        profile = conf['tool']['qgis-plugin']['dev']['profile']
    except KeyError:
        profile = 'default'
    return Path.home() / f'.local/share/QGIS/QGIS3/profiles/{profile}'


if __name__ == "__main__":
    app()
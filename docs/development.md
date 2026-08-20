# Development

This plugin uses [setuptools], [typer] and [black].

The general instructions for development are:

-  Fork the code repository
-  Clone your fork locally
-  Create a virtual environment and install the plugin and its development
   dependencies into it with

   ```
   cd qgis_geonode
   python3 -m venv --system-site-packages .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip  # pip >= 25.1 is needed for --group
   python -m pip install -e . --group dev
   ```

   The `--system-site-packages` flag lets the virtual environment see the QGIS
   Python bindings that are installed system-wide, which is what the tests need.

-  On Windows, QGIS does not provide the Qt bindings system-wide, so they have to
   be installed into the virtual environment as well. Add the extra that matches
   the QGIS version you are targeting:

   ```
   python -m pip install -e ".[qt5]" --group dev   # QGIS 3.x
   python -m pip install -e ".[qt6]" --group dev   # QGIS 4.x
   ```

   Both extras are declared with `sys_platform == 'win32'` markers, so they are
   no-ops on Linux and macOS and safe to use on any platform.

-  Work on a feature/bug on a new branch
-  When ready, submit a PR for your code to be reviewed and merged


## pluginadmin

This plugin comes with a `pluginadmin.py` python module which provides a CLI with commands useful for development. 
It is used to perform all operations related to the plugin:

- Install the plugin to your local QGIS user profile
- Build a zip of the plugin
- Generate the plugin metadata and the custom plugin repo XML
- etc.

It is run inside the virtual environment. As such it must be invoked with the
environment activated:

```
# get an overview of existing commands
python pluginadmin.py --help
```

!!! note
    Building the plugin shells out to `pyside6-rcc` to compile the Qt resources,
    so the virtual environment's `bin` (or `Scripts`, on Windows) directory needs
    to be on your `PATH`. Activating the environment takes care of that;
    calling `.venv/bin/python pluginadmin.py build` without activating does not.

## Install plugin into your local QGIS python plugins directory

When developing, in order to try out the plugin locally you need to 
call the `python pluginadmin.py install` command. This command will copy all files into your 
local QGIS python plugins directory. Upon making changes to the code you
will need to call this installation command again and potentially also restart QGIS.

!!! note
    Restarting QGIS is necessary because this plugin adds an additional data source provider to QGIS and there is 
    currently no way to reload the available providers without restarting QGIS.


```
python pluginadmin.py install
```


## Running tests

Tests are made with [pytest] and [pytest-qt]. What they need, before anything else:

- **The QGIS Python bindings and the matching Qt bindings.** The tests
  `import qgis.core` and go through `qgis.PyQt`, and a session-scoped autouse
  fixture in `test/conftest.py` builds a real `QgsApplication`. These bindings are
  *not* installable from PyPI - they come from a QGIS installation. QGIS 3.x
  brings PyQt5, QGIS 4.x brings PyQt6; the plugin supports both.
- **`xvfb`**, so the Qt widgets can be exercised headlessly ([pytest-xvfb] picks
  it up automatically). The official QGIS images already have it; on Debian and
  Ubuntu it is `apt install xvfb`. Without it, the tests run against your normal
  display.
- If QGIS lives somewhere unusual, point `QGIS_PREFIX_PATH` at it (it defaults to
  `/usr`), since the fixture passes it to `QgsApplication.setPrefixPath()`.

There are two ways to satisfy that: use the QGIS installed on your machine, or
run inside one of the official QGIS Docker images.

### Option 1 - against the QGIS installed on your system

The virtual environment has to be able to see the system-wide bindings, which is
what the `--system-site-packages` flag in the setup instructions above is for.
With that environment activated:

```
pytest
```

To confirm the bindings really are visible before hunting for other causes:

```
python -c "import qgis.core; from qgis.PyQt.QtCore import QT_VERSION_STR; \
    print(qgis.core.Qgis.QGIS_VERSION, '- Qt', QT_VERSION_STR)"
```

If that prints a `ModuleNotFoundError`, the environment was created without
`--system-site-packages`. Recreate it:

```
deactivate
rm -rf .venv
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e . --group dev
```

### Option 2 - inside an official QGIS container

This needs no QGIS on the host and is the closest thing to what CI does. These
are the images the CI matrix uses:

| image | QGIS | Qt | Python |
| --- | --- | --- | --- |
| `qgis/qgis:ltr-noble` | 3.44 LTR | 5.15 | 3.12 |
| `qgis/qgis:stable-trixie` | 4.x | 6.8 | 3.13 |

From the repository root:

```
docker run --rm -it \
  -v "$PWD":/plugin -w /plugin \
  -u "$(id -u):$(id -g)" -e HOME=/tmp/home \
  qgis/qgis:ltr-noble \
  bash -c '
    python3 -m venv --system-site-packages /tmp/venv
    /tmp/venv/bin/python -m pip install --upgrade pip
    /tmp/venv/bin/python -m pip install -e . --group dev
    /tmp/venv/bin/python -m pytest
  '
```

Swap the image name to run the same suite against the other QGIS major version.
Why the invocation looks like that:

- `-u "$(id -u):$(id -g)"` runs as you rather than as root, so the files the run
  leaves in the bind mount (`.pytest_cache`, `*.egg-info`) stay yours instead of
  needing `sudo` to clean up.
- `-e HOME=/tmp/home` provides a writable home. The fixture creates a QGIS user
  profile under `~/.local/share/QGIS`, and pip wants a cache directory.
- The virtualenv goes in `/tmp`, not in the mounted repository, so it cannot
  collide with the `.venv` you use on the host - that one is built against a
  different Python and Qt.
- `pip install --upgrade pip` first because the images ship pip 24.0, while
  `--group` needs pip 25.1 or newer.
- No `[qt5]` / `[qt6]` extra is needed: those exist for Windows only (they carry
  `sys_platform == 'win32'` markers) and the container already provides Qt.
- Always invoke pytest as `python -m pytest` from the virtualenv. A bare `pytest`
  can resolve to the distribution's `/usr/bin/pytest`, which runs under the
  system interpreter where the virtualenv's packages are invisible.

### Notes

`[tool.pytest.ini_options]` in `pyproject.toml` sets `--verbose --exitfirst`, so a
run stops at the first failure. Pass `-o addopts=""` to see every failure in one
go. CI additionally passes `--suppress-no-test-exit-code`.

Some troubleshooting:

| symptom | cause |
| --- | --- |
| `ModuleNotFoundError: No module named 'qgis'` | the virtualenv cannot see the system packages - recreate it with `--system-site-packages` |
| `ModuleNotFoundError` for a dev dependency (e.g. `flask`) | a bare `pytest` from `PATH` ran under the system interpreter - use `python -m pytest` |
| `AttributeError: type object 'Qt' has no attribute ...` | an unscoped Qt5-style enum reached a Qt6 run - see `scripts/pyqt5_to_pyqt6_pass2.py` |
| `test_get_success` fails on its own, once | the `mock_geonode_server` fixture starts the server process without waiting for the port to accept connections, so a slow start loses the race - re-run |


## Contributing

We welcome contributions from everybody but ask that the following process be adhered 
to:

1. Find (or open) the issue that describes the problem that you want to help solving. 
   Make a mention in the issue that you are working on a solution
   
2. Fork this repo and work on a solution to the problem. Remember to add passing 
   automated tests to attest that the problem has been fixed 
   
3. Run your code through the [black] formatter before submitting your PR. Otherwise 
   the CI pipeline may fail, and we will request that you fix it before merging. This 
   is how we run black in our CI pipeline:
   
   ```
   black src/qgis_geonode
   ```
   

## Releasing new versions

This plugin uses an automated release process that is based upon 
[github actions](https://docs.github.com/en/free-pro-team@latest/actions). 
New versions shall be released under the [semantic versioning](https://semver.org/) 
contract.

In order to have a new version of the plugin release:

- Be sure to have updated the `CHANGELOG.md`
  
- Be sure to have updated the version on the `pyproject.toml` file, by modifying
  the `project.version` key
  
- Create a new git annotated tag and push it to the repository. The tag name must 
  follow the `v{major}.{minor}.{patch}` convention, for example:

```
git tag -a -m 'version 0.3.2' v0.3.2
git push origin v0.3.2
```
  
- Github actions will take it from there. The new release shall appear in the custom 
  QGIS plugin repo shortly


[setuptools]: https://setuptools.pypa.io/
[typer]: https://typer.tiangolo.com/
[black]: https://github.com/psf/black
[proposed]: https://github.com/borysiasty/plugin_reloader/pull/22
[pytest]: https://docs.pytest.org/en/latest/
[pytest-qt]: https://github.com/pytest-dev/pytest-qt
[pytest-xvfb]: https://github.com/The-Compiler/pytest-xvfb

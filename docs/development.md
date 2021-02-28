# Development

This plugin uses [poetry], [typer] and [black].

The general instructions for development are:

-  Fork the code repository
-  Clone your fork locally
-  Install poetry
-  Install the plugin dependencies into a new virtual env with
   
   ```
   cd qgis_geonode
   poetry install
   ```
   
-  Work on a feature/bug on a new branch
-  When ready, submit a PR for your code to be reviewed and merged


## pluginadmin

This plugin comes with a `pluginadmin.py` python module which provides a CLI with commands useful for development. 
It is used to perform all operations related to the plugin:

- Install the plugin to your local QGIS user profile
- Ensure your virtual env has access to the QGIS Python bindings
- Build a zip of the plugin
- etc.

It is run inside the virtual environment created by poetry. As such it must be invoked like this:

```
# get an overview of existing commands
poetry run python pluginadmin.py --help
```

## Install plugin into your local QGIS python plugins directory

When developing, in order to try out the plugin locally you need to 
call `poetry run python pluginadmin.py install` command. This command will copy all files into your 
local QGIS python plugins directory. Upon making changes to the code you
will need to call this installation command again and potentially also restart QGIS.

!!! note
    Restarting QGIS is necessary because this plugin adds an additional data source provider to QGIS and there is 
    currently no way to reload the available providers without restarting QGIS.


```
poetry run python pluginadmin.py install
```


## Running tests

Tests are made with [pytest] and [pytest-qt]. In order to be able to run the tests, 
the Python virtual environment needs to have the QGIS Python bindings available. 
This can be achieved by running:

!!! note
If your QGIS is in a non-standard location, you can set these env variables before running the command:

    - `PYQT5_DIR_PATH` - location of PyQt5. Defaults to `/usr/lib/python3/dist-packages/PyQt5`
    - `SIP_DIR_PATH` - Location of the SIP package. Defaults to `/usr/lib/python3/dist-packages`
    - `QGIS_PYTHON_DIR_PATH` - Location of the QGIS Python bindings. Defaults to `/usr/lib/python3/dist-packages/qgis`

```
poetry run python pluginadmin.py install-qgis-into-venv
```

Installing QGIS Python bindings into the Python virtual environment only needs to be done once.


Finally, run tests with:

``
poetry run pytest
```


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
   poetry run black src/qgis_geonode
   ```
   

## Releasing new versions

This plugin uses an automated release process that is based upon 
[github actions](https://docs.github.com/en/free-pro-team@latest/actions). 
New versions shall be released under the [semantic versioning](https://semver.org/) 
contract.

In order to have a new version of the plugin release:

- Be sure to have updated the `CHANGELOG.md`
  
- Be sure to have updated the version on the `pyproject.toml` file. You can either 
  manually modify the `tool.poetry.version` key or you can run the 
  `poetry version {version specifier}` command
  
- Create a new git annotated tag and push it to the repository. The tag name must 
  follow the `v{major}.{minor}.{patch}` convention, for example:

```
git tag -a -m 'version 0.3.2' v0.3.2
git push origin v0.3.2
```
  
- Github actions will take it from there. The new release shall appear in the custom 
  QGIS plugin repo shortly


[poetry]: https://python-poetry.org/
[typer]: https://typer.tiangolo.com/
[black]: https://github.com/psf/black
[proposed]: https://github.com/borysiasty/plugin_reloader/pull/22
[pytest]: https://docs.pytest.org/en/latest/
[pytest-qt]: https://github.com/pytest-dev/pytest-qt
# Development

This plugin uses [poetry], [typer] and [black].

1. Fork the code repository
2. Clone your fork locally
3. Install poetry
4. Install the plugin dependencies into a new virtual env with

  ```
  cd qgis_geonode
  poetry install
  ```

5. The plugin comes with a `pluginadmin.py` python module which provides a nice CLI
  with commands useful for development:

  ```
  poetry run python pluginadmin.py --help
  
  # install plugin into your local QGIS python plugins directory
  poetry run python pluginadmin.py install
  
  
  poetry run python pluginadmin.py install-qgis-into-venv
  ```

6. When manually trying out the plugin locally you just need to call
  `poetry run python pluginadmin.py install`. This command will copy all files into 
   your local QGIS python plugins directory.
   
   Alternatively, the [plugin reloader] QGIS plugin can be used as a means to install 
   and reload the plugin. The functionality that allows re-running the poetry install 
   command is currently in a [proposed] state, so you may install plugin reloader 
   directly from the github fork mentioned in the above pull request


## Running tests

Tests are made with [pytest] and [pytest-qt]. They can be ran with:

```
# optionally create a QGIS_PREFIX_PATH env variable, if your QGIS is self-compiled
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
   the CI pipeline may fail, and we will request that you fix it before merging
   

## Releasing new versions

This plugin uses an automated release process that is based upon 
[github actions](https://docs.github.com/en/free-pro-team@latest/actions). 
New versions shall be released under the [semantic versioning](https://semver.org/) 
contract.

In order to have a new version of the plugin release:

- [] Be sure to have updated the `CHANGELOG`
  
- [] Be sure to have updated the version on the `pyproject.toml` file. You can either 
  manually modify the `tool.poetry.version` key or you can run the 
  `poetry version {version specifier}` command
  
- [ ] Create a new git annotated tag and push it to the repository. The tag name must 
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
[plugin reloader]: https://github.com/borysiasty/plugin_reloader
[proposed]: https://github.com/borysiasty/plugin_reloader/pull/22
[pytest]: https://docs.pytest.org/en/latest/
[pytest-qt]: https://github.com/pytest-dev/pytest-qt

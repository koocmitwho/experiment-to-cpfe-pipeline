def test_package_imports_with_version():
    import experiment_to_cpfe
    from pathlib import Path
    import tomllib

    metadata = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))
    assert experiment_to_cpfe.__version__ == metadata['project']['version']


def test_synthetic_fixture_path_is_repo_relative(synthetic_example_dir):
    assert synthetic_example_dir.name == "synthetic_minimal"


def test_specific_errors_share_pipeline_base():
    from experiment_to_cpfe.errors import (
        ArtifactError,
        ConfigurationError,
        PipelineError,
        SolverError,
        ValidationError,
    )

    assert issubclass(ConfigurationError, PipelineError)
    assert issubclass(ValidationError, PipelineError)
    assert issubclass(ArtifactError, PipelineError)
    assert issubclass(SolverError, PipelineError)

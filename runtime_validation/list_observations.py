"""Runtime element types of exact built-in lists, with one index per type."""
from runtime_validation.python_execution import type_name


def sample_list(value):
    # Snapshot before inspecting types, including when other threads share this list.
    sample = list.copy(value)
    first_index = {}
    for index, element in enumerate(sample):
        first_index.setdefault(type_name(element), index)
    return {'total': len(sample), 'checked': len(sample), 'first_index': first_index}


def merge_samples(destination, samples):
    for name, sample in samples.items():
        combined = destination.setdefault(name, {'total': 0, 'checked': 0, 'first_index': {}})
        combined['total'] += sample['total']
        combined['checked'] += sample['checked']
        for kind, index in sample['first_index'].items():
            combined['first_index'].setdefault(kind, index)

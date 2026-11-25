"""Bounded observations of exact built-in lists at Python function entry."""
from runtime_validation.python_execution import type_name


SAMPLE_LIMIT = 32


def sample_list(value):
    # Callers pass exact lists. Slicing avoids user iteration and takes a bounded copy.
    total = len(value)
    sample = value[:SAMPLE_LIMIT]
    first_index = {}
    for index, element in enumerate(sample):
        first_index.setdefault(type_name(element), index)
    return {'total': total, 'checked': len(sample), 'first_index': first_index}


def merge_samples(destination, samples):
    for name, sample in samples.items():
        combined = destination.setdefault(name, {'total': 0, 'checked': 0, 'first_index': {}})
        combined['total'] += sample['total']
        combined['checked'] += sample['checked']
        for kind, index in sample['first_index'].items():
            combined['first_index'].setdefault(kind, index)

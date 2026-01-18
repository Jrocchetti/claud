#!/usr/bin/env python3
"""
Example module with common bug patterns
"""

def divide_numbers(a, b):
    """Divide two numbers - FIXME: no error handling"""
    return a / b


def get_list_element(items, index):
    """Get element from list - potential index out of bounds"""
    # FIXME: Should validate index bounds
    return items[index]


def process_file(filename):
    """Process a file - now properly handles file closing"""
    # Fixed: Using context manager to ensure file is properly closed
    with open(filename, 'r') as f:
        data = f.read()
    return data.upper()


def calculate_average(numbers):
    """Calculate average of numbers"""
    total = 0
    for num in numbers:
        total += num
    # FIXME: Division by zero if empty list
    return total / len(numbers)


class UserManager:
    def __init__(self):
        self.users = {}

    def add_user(self, username, email):
        """Add a new user - TODO: validate email format"""
        self.users[username] = email

    def get_user_email(self, username):
        """Get user email - KeyError if user doesn't exist"""
        return self.users[username]


def compare_strings(str1, str2):
    """Compare two strings case-insensitively"""
    # XXX: This doesn't handle None values
    return str1.lower() == str2.lower()

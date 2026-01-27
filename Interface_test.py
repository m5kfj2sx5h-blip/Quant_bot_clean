#!/usr/bin/env python3
"""
Interface Compatibility Checker for QUANT_bot-2.1
Verifies that system_orchestrator.py can correctly interact with all other modules.
"""

import ast
import inspect
import sys
import os
from typing import Dict, List, Set

def get_class_methods(filepath: str, class_name: str = None) -> Dict[str, Set[str]]:
    """Extract all method names from a class in a Python file."""
    try:
        with open(filepath, 'r') as f:
            tree = ast.parse(f.read())
        
        classes = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = set()
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        methods.add(item.name)
                classes[node.name] = methods
        
        if class_name:
            return {class_name: classes.get(class_name, set())}
        return classes
        
    except Exception as e:
        print(f"  ❌ Error reading {filepath}: {e}")
        return {}

def check_orchestrator_imports() -> Dict[str, List[str]]:
    """Check what classes/functions system_orchestrator.py imports from each module."""
    imports = {}
    try:
        with open('system_orchestrator.py', 'r') as f:
            content = f.read()
            tree = ast.parse(content)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports[alias.name] = ['*']  # Wildcard import
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                imports[module] = [alias.name for alias in node.names]
        
        return imports
        
    except Exception as e:
        print(f"❌ Error reading system_orchestrator.py: {e}")
        return {}

def check_method_calls(orchestrator_path: str, target_class: str) -> Set[str]:
    """Extract all method calls on a specific class instance from the orchestrator."""
    calls = set()
    try:
        with open(orchestrator_path, 'r') as f:
            content = f.read()
            tree = ast.parse(content)
        
        for node in ast.walk(tree):
            # Look for pattern: self.health_monitor.some_method()
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    attr_expr = node.func
                    # Check if it's like self.health_monitor.xxx
                    if (isinstance(attr_expr.value, ast.Attribute) and 
                        isinstance(attr_expr.value.value, ast.Name) and
                        attr_expr.value.value.id == 'self'):
                        
                        instance_name = attr_expr.value.attr  # e.g., 'health_monitor'
                        method_name = attr_expr.attr  # e.g., 'check_system_health'
                        
                        # We're looking for calls on this specific instance
                        if instance_name == target_class.lower().replace('monitor', '_monitor').replace('context', '_context'):
                            calls.add(method_name)
    
    except Exception as e:
        print(f"❌ Error analyzing method calls: {e}")
    
    return calls

def main():
    print("=" * 80)
    print("INTERFACE COMPATIBILITY DIAGNOSTIC - QUANT_bot-2.1")
    print("=" * 80)
    
    # Check orchestrator imports first
    print("\n📦 1. Checking orchestrator imports...")
    imports = check_orchestrator_imports()
    
    # Modules to check based on your system
    modules_to_check = [
        ('health_monitor.py', 'HealthMonitor'),
        ('market_context.py', 'MarketContext'),
        ('order_executor.py', 'OrderExecutor'),
        ('data_feed.py', 'DataFeed'),
        ('exchange_wrappers.py', 'ExchangeWrapperFactory'),
    ]
    
    all_good = True
    
    for filepath, class_name in modules_to_check:
        if not os.path.exists(filepath):
            print(f"\n⚠️  File not found: {filepath}")
            continue
            
        print(f"\n🔍 Checking {filepath} (class: {class_name})...")
        
        # Get methods available in the class
        class_methods = get_class_methods(filepath, class_name)
        
        if not class_methods or class_name not in class_methods:
            print(f"  ❌ Class '{class_name}' not found or has no methods in {filepath}")
            all_good = False
            continue
        
        methods = class_methods[class_name]
        print(f"  ✅ Found {len(methods)} methods in {class_name}")
        
        # Check what the orchestrator calls on instances of this class
        instance_var_name = ''
        if class_name == 'HealthMonitor':
            instance_var_name = 'health_monitor'
        elif class_name == 'MarketContext':
            instance_var_name = 'market_context'
        elif class_name == 'OrderExecutor':
            instance_var_name = 'order_executor'
        elif class_name == 'DataFeed':
            instance_var_name = 'data_feed'
        
        if instance_var_name:
            called_methods = check_method_calls('system_orchestrator.py', instance_var_name)
            missing_methods = called_methods - methods
            
            if missing_methods:
                print(f"  ❌ MISSING METHODS in {class_name}: {missing_methods}")
                print(f"     Orchestrator calls these but they don't exist in the class.")
                all_good = False
            else:
                print(f"  ✅ All called methods exist in {class_name}")
        
        # Show first 10 methods for verification
        print(f"  Sample methods: {sorted(list(methods))[:10]}")
    
    print("\n" + "=" * 80)
    if all_good:
        print("✅ ALL MODULES APPEAR COMPATIBLE")
    else:
        print("❌ INTERFACE MISMATCHES DETECTED")
        print("\nRecommended action: For each missing method, either:")
        print("  1. Add the method to the corresponding class, or")
        print("  2. Change the method call in system_orchestrator.py")
    print("=" * 80)

if __name__ == "__main__":
    # Change to your QUANT_bot-2.1 directory
    if not os.path.exists('system_orchestrator.py'):
        print("Please run this script from your QUANT_bot-2.1 directory")
        sys.exit(1)
    
    main()
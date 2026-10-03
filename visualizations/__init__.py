"""Crow-Eye visualizations.

Chart/visualization layer for parsed artifact data. Each visualization is a
React + chart.js frontend (react-viz) hosted in a QWebEngineView and fed by a
QWebChannel bridge that queries the case databases read-only.

The first visualization is the SRUM activity contribution chart - a GitHub-style
calendar heatmap of daily system-resource activity, with a metric selector, a
day drill-down, and multi-term search.
"""

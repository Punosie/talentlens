"""Benchmark helpers for TalentLens local-AI accuracy work (see benchmarks/README.md).

Everything here reads a frozen COPY of a library database. Nothing writes to the user's library,
the CV folder or any .env file. Outputs that contain real names go under
%LOCALAPPDATA%\\TalentLens\\benchmarks, never into git.
"""

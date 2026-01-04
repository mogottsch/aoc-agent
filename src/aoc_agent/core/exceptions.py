class AOCAgentError(Exception):
    pass


class AOCError(AOCAgentError):
    pass


class ExecutionError(AOCAgentError):
    pass


class SubmissionError(AOCAgentError):
    pass


class InfrastructureError(AOCAgentError):
    pass

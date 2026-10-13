"""The one error type the method raises when a step cannot complete."""


class MeetingDiarizationError(Exception):
    """A step failed. The message says which step and why.

    The live pipeline carried on after several of these failures. The
    published version stops instead, so a reader never gets a result that
    looks fine but is not.
    """

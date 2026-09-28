from typing import Any

from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from access.models import ROLE_RANK, FundMembership


class FundRolePermission(BasePermission):
    """The caller must hold at least `view.required_role` on the fund this request touches.

    Views provide get_fund_id(), which resolves the fund from the URL: directly for
    /funds/{id}/..., or through the object (account, transfer) otherwise. That object-level
    resolution is what prevents IDOR: you can't reach another fund's account by its id.
    """

    message = "Your role on this fund does not allow this action."

    def has_permission(self, request: Request, view: Any) -> bool:
        if not (request.user and request.user.is_authenticated):
            return False  # → 401
        membership = (
            FundMembership.objects.filter(user=request.user, fund_id=view.get_fund_id())
            .select_related("fund")
            .first()
        )
        if membership is None:
            raise NotFound()  # don't confirm the fund exists to non-members
        request.fund_membership = membership  # type: ignore[attr-defined]
        return ROLE_RANK[membership.role] >= ROLE_RANK[view.required_role]  # → 403 if False


def membership_of(request: Request) -> FundMembership:
    membership = getattr(request, "fund_membership", None)
    if membership is None:
        raise RuntimeError("FundRolePermission has not run for this view")
    return membership

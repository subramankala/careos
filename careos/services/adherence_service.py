from careos.services.win_service import WinService


class AdherenceService:
    def __init__(self, win_service: WinService) -> None:
        self.win_service = win_service

    def get_daily_summary(self, patient_id: str):
        return self.win_service.adherence_summary(patient_id)

from django.core.management.commands.loaddata import Command as LoadDataCommand
from django.db.models.signals import post_save, pre_save, post_delete, pre_delete, m2m_changed
from django.db import transaction

class Command(LoadDataCommand):
    help = 'Load data without triggering any signals'

    def handle(self, *fixture_labels, **options):
        # Store all signal receivers
        saved_receivers = {}
        
        signals = [pre_save, post_save, pre_delete, post_delete, m2m_changed]
        
        for signal in signals:
            # Save current receivers
            saved_receivers[signal] = signal.receivers[:]
            # Clear all receivers
            signal.receivers = []
        
        try:
            # Load fixtures
            with transaction.atomic():
                super().handle(*fixture_labels, **options)
        finally:
            # Restore all signal receivers
            for signal in signals:
                signal.receivers = saved_receivers[signal]
        
        self.stdout.write(self.style.SUCCESS('Successfully loaded data without triggering signals'))
